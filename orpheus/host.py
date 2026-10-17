"""Public Hermes lifecycle adapter; no private agents or mutable host configuration."""
from __future__ import annotations

import dataclasses
import enum
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from .deployment import validate_subagent, secure_state_directory, secure_sqlite_files


class HostError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def plain(value):
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


class SubagentAdapter:
    """Persist before submission; delegate parent ownership checks to the host.

    ``verified_settings`` is operator-managed deployment evidence, not plugin
    discovery or a provider capability guess. Effort additionally requires the
    public per-launch-v1 extension shipped separately in compat/.
    """
    def __init__(self, lifecycle, state_dir, deployment=None, *, redact_literals=None):
        self.lifecycle = lifecycle
        self.deployment = deployment or {}
        validate_subagent(self.deployment)
        self.redact_literals = [] if redact_literals is None else redact_literals
        if not isinstance(self.redact_literals, list) or any(not isinstance(x, str) or not x for x in self.redact_literals):
            raise HostError('invalid_config', 'redact_literals must contain nonempty strings.')
        path = secure_state_directory(state_dir)
        secure_sqlite_files(path / 'subagents.sqlite')
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path / 'subagents.sqlite', check_same_thread=False)
        secure_sqlite_files(path / 'subagents.sqlite')
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('CREATE TABLE IF NOT EXISTS children (id TEXT PRIMARY KEY, selection TEXT NOT NULL, state TEXT NOT NULL, handle TEXT, result TEXT, updated REAL NOT NULL)')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(children)')}
        if 'expires_at' not in columns:
            self.db.execute('ALTER TABLE children ADD COLUMN expires_at REAL')
            self.db.execute('UPDATE children SET expires_at=updated+?', (7 * 86400,))
        self.db.execute('CREATE INDEX IF NOT EXISTS child_expiry ON children(expires_at) WHERE expires_at IS NOT NULL')
        self.db.commit()
        self._stop = threading.Event()
        self._maintenance_thread = threading.Thread(target=self._maintain, daemon=True, name='orpheus-child-retention')
        self._maintenance_thread.start()

    def _maintain(self):
        while not self._stop.wait(10):
            try:
                self.expire_records()
            except (sqlite3.Error, OSError):
                # A transient lock must not stop subsequent expiry passes.
                continue

    def expire_records(self, now=None):
        now = time.time() if now is None else now
        terminal = {'SUCCEEDED', 'FAILED', 'CANCELLED', 'INTERRUPTED', 'completed', 'failed', 'cancelled'}
        with self.lock:
            rows = self.db.execute('SELECT id,state FROM children WHERE expires_at IS NOT NULL AND expires_at <= ? ORDER BY expires_at LIMIT 256', (now,)).fetchall()
            for request_id, state in rows:
                if state in terminal:
                    self.db.execute('DELETE FROM children WHERE id=?', (request_id,))
                else:
                    # Preserve reconciliation authority, but erase retained inputs/results.
                    self.db.execute("UPDATE children SET selection='{}',result=NULL,expires_at=NULL WHERE id=?", (request_id,))
            self.db.commit()
        return len(rows)

    def close(self):
        self._stop.set()
        self._maintenance_thread.join(timeout=2)
        with self.lock:
            self.db.close()

    def capabilities(self):
        extended = False
        fallback_control = False
        probe = getattr(self.lifecycle, 'capabilities', None)
        if callable(probe):
            try:
                capabilities = probe()
                extended = capabilities.get('reasoning_effort') == 'per-launch-v1'
                fallback_control = capabilities.get('disable_fallback') == 'per-launch-v1'
            except Exception:
                pass
        return {'model': 'unverified', 'provider': 'unverified',
                'effort': 'unverified' if extended else 'unsupported',
                'effort_contract': extended, 'fallback_control': fallback_control, 'restart_recovery': 'unsupported',
                'reason': 'Launch requires deployment-specific verified settings and disabled provider fallback.'}

    def preflight(self, selection):
        settings = selection['resolved']
        permitted = {'provider', 'model', 'effort', 'instructions', 'allowed_toolsets'}
        if set(settings) - permitted:
            raise HostError('unsupported_field', 'Native launch includes unsupported fields.')
        if 'effort' in settings and not self.capabilities()['effort_contract']:
            raise HostError('unsupported_effort', 'Host lacks verified public per-launch effort contract.')
        if settings.get('allowed_toolsets') == []:
            raise HostError('unsupported_tools', 'An empty native toolset means inheritance and cannot enforce no tools.')
        if not self.capabilities()['fallback_control'] and self.deployment.get('fallback_disabled') is not True:
            raise HostError('unverified_fallback', 'Provider fallback must be verified disabled before launch.')
        wanted = {k: settings[k] for k in ('provider', 'model', 'effort') if k in settings}
        if wanted not in self.deployment.get('verified_settings', []):
            raise HostError('unverified_settings', 'Exact provider/model/effort requires deployment verification.')
        if 'allowed_toolsets' in settings:
            allowed = self.deployment.get('allowed_toolsets', [])
            if not set(settings['allowed_toolsets']).issubset(allowed):
                raise HostError('unauthorized_tools', 'Requested toolsets exceed operator scope.')

    def launch(self, selection, task, context=None):
        self.preflight(selection)
        settings = selection['resolved']
        context_parts = []
        if settings.get('instructions'):
            context_parts.append('Preset instructions:\n' + settings['instructions'])
        if context:
            context_parts.append('Explicit task context:\n' + json.dumps(context, ensure_ascii=False, sort_keys=True))
        request_id = selection.get('request_id') or str(uuid.uuid4())
        request = {'goal': task, 'model': settings['model'], 'provider': settings['provider'],
                   'correlation_id': request_id, 'metadata': {'orpheus_request_id': request_id}}
        if self.capabilities()['fallback_control']:
            request['disable_fallback'] = True
        if context_parts:
            request['context'] = '\n\n'.join(context_parts)
        for key in ('effort', 'allowed_toolsets'):
            if key in settings:
                request['reasoning_effort' if key == 'effort' else key] = settings[key]
        if len(task) > 16000 or len(request.get('context', '')) > 32000:
            raise HostError('input_too_large', 'Task/context exceeds the public native lifecycle bounds.')
        with self.lock:
            self.db.execute('INSERT INTO children (id,selection,state,handle,result,updated,expires_at) VALUES (?, ?, ?, NULL, NULL, ?, ?)',
                            (request_id, json.dumps(selection), 'starting', time.time(), time.time() + 7 * 86400))
            self.db.commit()
        try:
            handle = plain(self.lifecycle.launch(request))
        except Exception as exc:
            # Any exception after invocation could follow an accepted launch.
            with self.lock:
                self.db.execute('UPDATE children SET state=?, updated=? WHERE id=?', ('unknown', time.time(), request_id))
                self.db.commit()
            return {'request_id': request_id, 'state': 'unknown', 'error': 'launch_outcome_unknown', 'observed': None}
        with self.lock:
            self.db.execute('UPDATE children SET state=?,handle=?,updated=? WHERE id=?',
                            ('running', json.dumps(handle), time.time(), request_id))
            self.db.commit()
        return {'request_id': request_id, 'state': 'running', 'resolved': settings,
                'launch_accepted': {k: handle.get(k) for k in ('model', 'provider')},
                'observed': None}

    def _owned(self, request_id):
        with self.lock:
            row = self.db.execute('SELECT handle,result,updated FROM children WHERE id=?', (request_id,)).fetchone()
        if not row or not row[0]:
            raise HostError('unavailable', 'Run is unavailable or its ownership cannot be verified.')
        handle = json.loads(row[0])
        snapshot = plain(self.lifecycle.status(handle))
        if snapshot.get('diagnostic') == 'UNKNOWN_HANDLE' or snapshot.get('state') == 'UNKNOWN':
            raise HostError('unavailable', 'Run is unavailable or its ownership cannot be verified.')
        return handle, snapshot, row

    def status(self, request_id):
        handle, snapshot, row = self._owned(request_id)
        result = plain(self.lifecycle.result(handle))
        result.pop('handle', None)  # native capabilities never leave protected storage
        def redact(value):
            if isinstance(value, str):
                for literal in self.redact_literals:
                    value = value.replace(literal, '[REDACTED]')
                return value
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value
        result = redact(result)
        snapshot.pop('handle', None)
        if result.get('ready') and result.get('completed_at') is not None and result['completed_at'] < time.time() - 7 * 86400:
            return {'request_id': request_id, **snapshot, 'result': None, 'observed': None, 'result_availability': 'expired'}
        if result.get('ready'):
            raw = str(result.get('summary') or '').encode('utf-8')
            result['summary'] = raw[:262144].decode('utf-8', errors='ignore')
            result['truncated'] = len(raw) > 262144
            result['observed_bytes'] = len(raw)
            with self.lock:
                self.db.execute("UPDATE children SET state=?,result=?,updated=?,expires_at=CASE WHEN state NOT IN ('SUCCEEDED','FAILED','CANCELLED','INTERRUPTED') THEN ? ELSE expires_at END WHERE id=?",
                                (snapshot['state'], json.dumps(result), time.time(), time.time() + 7 * 86400, request_id))
                self.db.commit()
        return {'request_id': request_id, **snapshot, 'result': result, 'observed': None,
                'result_availability': 'available' if result.get('ready') else 'pending'}

    def cancel(self, request_id):
        handle, _, _ = self._owned(request_id)
        outcome = plain(self.lifecycle.cancel(handle, reason='Orpheus owner requested cancellation'))
        return {'request_id': request_id, 'cancellation': outcome,
                'state': 'cancellation_pending' if outcome.get('accepted') else 'unchanged'}
