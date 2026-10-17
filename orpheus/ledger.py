"""Transactional delivery ledger. Replay tombstones deliberately never expire."""
from __future__ import annotations
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from .deployment import secure_state_directory, secure_sqlite_files


class Conflict(ValueError):
    pass


class Ledger:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ':memory:':
            secure_state_directory(Path(self.path).parent)
            fd=os.open(self.path,os.O_CREAT | os.O_RDWR,0o600); os.close(fd)
            Path(self.path).chmod(0o600)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, scope TEXT NOT NULL, event_id TEXT,
          digest TEXT NOT NULL, replay_digest TEXT, state TEXT NOT NULL,
          generation INTEGER NOT NULL DEFAULT 1, lease REAL NOT NULL,
          created REAL NOT NULL, updated REAL NOT NULL, data TEXT NOT NULL,
          UNIQUE(scope,event_id), UNIQUE(scope,replay_digest));
        CREATE TABLE IF NOT EXISTS audit (
          id TEXT PRIMARY KEY, scope TEXT, reason TEXT NOT NULL, created REAL NOT NULL);
        ''')
        if 'retention_at' not in {r[1] for r in self.db.execute('PRAGMA table_info(runs)')}:
            self.db.execute('ALTER TABLE runs ADD COLUMN retention_at REAL')
        self.db.execute('CREATE INDEX IF NOT EXISTS runs_retention ON runs(retention_at) WHERE retention_at IS NOT NULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS acceptance_receipts (id TEXT PRIMARY KEY, dispatch_token TEXT NOT NULL, host_id TEXT NOT NULL, created REAL NOT NULL)')
        self.db.execute("UPDATE runs SET retention_at=updated+? WHERE state IN ('completed','failed','cancelled') AND retention_at IS NULL AND json_extract(data,'$.compacted') IS NULL",(7*86400,))
        self.db.execute("UPDATE runs SET retention_at=updated+? WHERE state='unknown' AND retention_at IS NULL AND json_extract(data,'$.compacted') IS NULL",(7*86400,))
        if self.path != ':memory:': secure_sqlite_files(self.path)

    def close(self):
        self.db.close()

    def _decode(self, row):
        if row is None:
            return None
        result = dict(row)
        result.update(json.loads(result.pop('data')))
        return result

    def get(self, request_id):
        return self._decode(self.db.execute('SELECT * FROM runs WHERE id=?', (request_id,)).fetchone())

    def reserve(self, scope, digest, snapshot, *, event_id=None, raw_replay=True):
        """Reserve both signed event and exact-body replay identities atomically."""
        now = time.time()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = None
            if event_id is not None:
                row = self.db.execute('SELECT * FROM runs WHERE scope=? AND event_id=?', (scope,event_id)).fetchone()
                if row and row['digest'] != digest:
                    raise Conflict('identity_body_conflict')
            if row is None and raw_replay:
                row = self.db.execute('SELECT * FROM runs WHERE scope=? AND replay_digest=?', (scope,digest)).fetchone()
            if row:
                self.db.execute('COMMIT')
                return self._decode(row), False
            rid = uuid.uuid4().hex
            self.db.execute('INSERT INTO runs (id,scope,event_id,digest,replay_digest,state,generation,lease,created,updated,data) VALUES (?,?,?,?,?,?,1,?,?,?,?)',
                            (rid,scope,event_id,digest,digest if raw_replay else None,'resolving',now+60,now,now,json.dumps(snapshot)))
            self.db.execute('COMMIT')
            return self.get(rid), True
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def change(self, rid, generation, states, new_state, **updates):
        """Fenced CAS. Expired owners cannot publish selector or launch results."""
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
            if not row or row['generation'] != generation or row['state'] not in states or row['lease'] < time.time():
                self.db.execute('COMMIT')
                return False
            data = json.loads(row['data'])
            if data.get('disposition')=='abandoned':
                updates={k:v for k,v in updates.items() if k not in {'result','result_availability','result_expires','result_observed','result_bytes','result_is_partial','truncated','task','context','payload','registry_snapshot'}}
            data.update(updates)
            self.db.execute('UPDATE runs SET state=?,updated=?,data=? WHERE id=?', (new_state,time.time(),json.dumps(data),rid))
            if (new_state in ('completed','failed','cancelled','unknown') and not data.get('compacted')) or 'result' in updates:
                self.db.execute('UPDATE runs SET retention_at=COALESCE(retention_at,?) WHERE id=?',(time.time()+7*86400,rid))
            self.db.execute('COMMIT')
            return True
        except BaseException:
            self.db.execute('ROLLBACK'); raise

    def publish_acceptance(self, rid, token, key, payload_digest, host_id):
        """Publish one immutable dispatch receipt, independently of worker leases.

        This is evidence from the sole dispatcher, not permission to dispatch again.
        New owners can reconcile it even after the dispatch lease expires.
        """
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            data=json.loads(row['data']) if row else {}
            if (data.get('dispatch_token'),data.get('idempotency_key'),data.get('payload_digest'))!=(token,key,payload_digest):
                self.db.execute('COMMIT'); return False
            receipt=self.db.execute('SELECT * FROM acceptance_receipts WHERE id=?',(rid,)).fetchone()
            if receipt and (receipt['dispatch_token']!=token or receipt['host_id']!=host_id):
                self.db.execute('COMMIT'); return False
            self.db.execute('INSERT OR IGNORE INTO acceptance_receipts VALUES (?,?,?,?)',(rid,token,host_id,time.time()))
            if row['state'] not in ('starting','unknown','running') or data.get('host_id',host_id)!=host_id:
                self.db.execute('COMMIT'); return False
            settings=data.get('payload',data.get('selection',{}))
            accepted={k:settings[k] for k in ('model','provider') if k in settings}
            data.update(host_id=host_id,launch_accepted=accepted)
            state='unknown' if data.get('disposition')=='abandoned' else 'running'
            self.db.execute('UPDATE runs SET state=?,data=?,updated=? WHERE id=?',(state,json.dumps(data),time.time(),rid))
            self.db.execute('COMMIT'); return True
        except BaseException:
            self.db.execute('ROLLBACK'); raise

    def claim(self, rid):
        """Renew ownership only after expiry; never authorizes another submit."""
        now = time.time()
        changed = self.db.execute('UPDATE runs SET generation=generation+1,lease=? WHERE id=? AND lease<?', (now+60,rid,now)).rowcount
        return self.get(rid) if changed else None

    def renew(self, rid, generation):
        return bool(self.db.execute('UPDATE runs SET lease=? WHERE id=? AND generation=? AND lease>=?', (time.time()+60,rid,generation,time.time())).rowcount)

    def cancel(self, rid):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
            if row and row['state'] not in ('completed','failed','cancelled'):
                data = json.loads(row['data']); data['cancel_requested'] = True
                state = 'cancelled' if row['state'] in ('resolving','selected') else row['state']
                # Revoking prelaunch generation guarantees late selection cannot submit.
                generation = row['generation'] + (state == 'cancelled')
                self.db.execute('UPDATE runs SET state=?,generation=?,updated=?,data=? WHERE id=?', (state,generation,time.time(),json.dumps(data),rid))
                if state=='cancelled': self.db.execute('UPDATE runs SET retention_at=? WHERE id=?',(time.time()+7*86400,rid))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK'); raise
        return self.get(rid)

    def abandon(self, rid):
        """Administrative disposition never fabricates a terminal execution result."""
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            if not row or row['state']!='unknown':
                self.db.execute('COMMIT'); return False
            data=json.loads(row['data'])
            data.setdefault('abandoned_at',time.time()); data['disposition']='abandoned'
            self.db.execute('UPDATE runs SET data=?,updated=? WHERE id=?',(json.dumps(data),time.time(),rid))
            if not data.get('compacted'):
                self.db.execute('UPDATE runs SET retention_at=COALESCE(retention_at,?) WHERE id=?',(data['abandoned_at']+7*86400,rid))
            self.db.execute('COMMIT'); return True
        except BaseException:
            self.db.execute('ROLLBACK'); raise

    def active(self):
        return [self._decode(row) for row in self.db.execute("SELECT * FROM runs WHERE state IN ('resolving','selected','starting','running','unknown') AND COALESCE(json_extract(data,'$.disposition'),'')!='abandoned' AND NOT (state='unknown' AND COALESCE(json_extract(data,'$.host_id'),'')='') AND NOT (state='unknown' AND COALESCE(json_extract(data,'$.error.code'),'') IN ('host_run_unavailable','target_identity_changed'))")]

    def audit(self, scope, reason):
        now=time.time()
        self.db.execute('INSERT INTO audit VALUES (?,?,?,?)',(uuid.uuid4().hex,scope,reason,now))
        self.db.execute('DELETE FROM audit WHERE created<?',(now-7*86400,))
        self.db.execute('DELETE FROM audit WHERE id IN (SELECT id FROM audit ORDER BY created DESC LIMIT -1 OFFSET 10000)')

    def expire_results(self):
        """Compact expired terminal/unknown data, retaining immutable launch evidence."""
        now=time.time()
        rows=self.db.execute('SELECT * FROM runs WHERE retention_at<=? ORDER BY retention_at LIMIT 1000',(now,)).fetchall()
        for row in rows:
            data=json.loads(row['data'])
            keep={k:data[k] for k in ('disposition','host_id','native_status','observed','error') if k in data}
            selection=data.get('selection',{})
            keep['selection']={k:selection[k] for k in ('registry_revision','preset_revision','preset_id','policy_id','policy_revision','tuple_id','model','provider','effort') if k in selection}
            if row['state'] not in ('completed','failed','cancelled') or data.get('disposition')=='abandoned':
                for key in ('abandoned_at','dispatch_token','idempotency_key','payload_digest','target','principal','cancel_requested','launch_accepted'):
                    if key in data: keep[key]=data[key]
                target=data.get('target_snapshot',{})
                keep['target_snapshot']={k:target[k] for k in ('url','principal') if k in target}
                for key in ('model','provider','effort'):
                    if key not in keep['selection'] and key in data.get('payload',{}): keep['selection'][key]=data['payload'][key]
            keep.update(compacted=True,result_availability='expired')
            changed=self.db.execute('UPDATE runs SET data=?,retention_at=NULL WHERE id=? AND data=?',(json.dumps(keep),row['id'],row['data'])).rowcount
            if changed and 'dispatch_token' not in keep: self.db.execute('DELETE FROM acceptance_receipts WHERE id=?',(row['id'],))
