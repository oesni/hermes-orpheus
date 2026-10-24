"""Host-observed model of the calling Hermes session.

The ``post_api_request`` lifecycle hook reports the model and provider Hermes used for each
successful provider response, keyed by session ID. A tool call is always produced by such a
response, so the latest observation for the calling session is the model that requested the
tool. Orpheus only exposes this value and offers it to selection policies that declare it; it
never changes a selection on its own.
"""
from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict

SESSION_FIELDS = frozenset({'session.model', 'session.provider', 'session.model_ref'})
DEFAULT_LIMIT = 4096


class SessionModels:
    """Bounded, thread-safe latest model observation per Hermes session ID.

    When full, the session observed least recently is evicted; reads do not refresh recency.
    """

    def __init__(self, limit=DEFAULT_LIMIT, clock=time.time):
        if type(limit) is not int or limit < 1:
            raise ValueError('limit must be a positive integer')
        self._limit = limit
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = OrderedDict()

    def observe(self, session_id=None, model=None, provider=None, ended_at=None, **_ignored):
        """``post_api_request`` observer: record and return nothing (observers' results are ignored).

        Hermes runs hook callbacks on worker threads, so two observations of one session can be
        delivered out of order. Order them by the host-computed response time ``ended_at`` (set
        before dispatch) and never let an older observation replace a newer one. A payload
        without a usable ``ended_at`` falls back to the local clock.
        """
        if not _text(session_id) or not _text(model) or not _text(provider):
            return None
        observed_at = ended_at if _finite(ended_at) else self._clock()
        entry = {'model': model, 'provider': provider, 'observed_at': observed_at}
        with self._lock:
            current = self._entries.get(session_id)
            if current is not None and current['observed_at'] > observed_at:
                return None
            self._entries[session_id] = entry
            self._entries.move_to_end(session_id)
            while len(self._entries) > self._limit:
                self._entries.popitem(last=False)
        return None

    def get(self, session_id):
        if not _text(session_id):
            return None
        with self._lock:
            entry = self._entries.get(session_id)
            return dict(entry) if entry is not None else None


def describe(entry, inventory):
    """Public view of an observation, with the inventory references naming the exact pair."""
    if entry is None:
        return None
    refs = sorted(ref for ref, model in inventory.items()
                  if model.get('model') == entry['model'] and model.get('provider') == entry['provider'])
    return {'provider': entry['provider'], 'model': entry['model'],
            'model_ref': refs[0] if len(refs) == 1 else None, 'matching_refs': refs,
            'observed_at': entry['observed_at']}


def selection_inputs(described):
    """``session.*`` selection values for a described observation; absent values are omitted."""
    if described is None:
        return {}
    values = {'session.model': described['model'], 'session.provider': described['provider'],
              'session.model_ref': described['model_ref']}
    return {name: value for name, value in values.items() if value is not None}


def _text(value):
    return isinstance(value, str) and bool(value)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)
