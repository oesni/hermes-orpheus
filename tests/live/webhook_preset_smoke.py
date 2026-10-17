"""Opt-in signed webhook -> fixed preset -> public Hermes Run API smoke test.

Run only against an isolated operator-verified Hermes API. No config is installed.
The caller supplies a credential through an environment variable, never an argv value.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from orpheus.config import Registry
from orpheus.ledger import Ledger
from orpheus.resolver import Resolver
from orpheus.webhook import RunClient, WebhookService

TASK = ('Review only this supplied function; do not call tools or change files. '
        'Contract: totals >= 10000 cents receive a 10% discount. '
        'Code: def discounted_total(total_cents): return total_cents * 90 // 100 '
        'if total_cents > 10000 else total_cents. '
        'Give the boundary input, actual, expected, and corrected operator.')
PRESETS = ('reviewer', 'auditor')


def require_checks_enabled():
    if sys.flags.optimize:
        raise RuntimeError('optimized_python_disables_verification')


def config(model, provider):
    presets, policies, routes = [], {}, []
    for name in PRESETS:
        instructions = ('Do not use tools, files, memory, or skills. Review only the supplied code. '
            'Return only JSON with keys preset_marker, input_cents, actual_cents, '
            'expected_cents, corrected_operator. Set preset_marker to ' + name + '.')
        presets.append({'id': name, 'purpose': 'Read-only synthetic review',
            'fields': {'model': {'mode': 'fixed', 'value': 'local'},
                       'instructions': {'mode': 'fixed', 'value': instructions}},
            'compatible_settings': {'review': {}}})
        policies[name] = {'entrypoint': 'webhook',
            'preset_selector': {'id': name + '-preset', 'kind': 'fixed', 'preset': name},
            'field_resolver': {'id': name + '-fields', 'kind': 'fixed', 'settings': 'review'}}
        routes.append({'id': name, 'policy': name, 'auth_profile': 'source',
            'security_scope': 'smoke-' + name, 'execution_target': 'local',
            'event_schema': {'event.task': {'source': 'body', 'pointer': '/task',
                'type': 'string', 'max_length': 4096, 'trust': 'payload'}},
            'routing_fields': [], 'task_fields': ['event.task'], 'receipt': {'kind': 'disabled'}})
    return {'schema_version': 1, 'inventory': {'models': {'local': {
        'model': model, 'provider': provider}}}, 'presets': presets,
        'policies': policies, 'webhooks': routes}


class RecordingRunClient(RunClient):
    """Record only synthetic payloads and public run identity, never HTTP credentials."""
    def __init__(self, targets):
        super().__init__(targets)
        self.calls = []
        self.statuses = {}

    async def submit(self, payload, key, target):
        entry = {'payload': payload, 'idempotency_key': key}
        self.calls.append(entry)
        result = await super().submit(payload, key, target)
        entry['run_id'] = result.get('run_id') or result.get('id')
        return result

    async def status(self, run_id, target):
        result = await super().status(run_id, target)
        self.statuses[run_id] = result
        return result


@asynccontextmanager
async def cancel_unfinished(host):
    try:
        yield
    finally:
        for call in host.calls:
            run_id = call.get('run_id')
            if run_id and host.statuses.get(run_id, {}).get('status') not in (
                    'completed', 'failed', 'cancelled', 'interrupted'):
                try:
                    await host.cancel(run_id, 'local')
                except Exception:
                    # Preserve the original failure; operator owns ambiguous cleanup.
                    print(json.dumps({'cleanup': 'cancel_unconfirmed', 'run_id': run_id}))


def finding(output):
    require_checks_enabled()
    text = output.strip()
    if text.startswith('```') and text.endswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    value = json.loads(text)
    assert isinstance(value, dict)
    for key, expected in {'input_cents': 10000, 'actual_cents': 10000,
                          'expected_cents': 9000, 'corrected_operator': '>='}.items():
        assert type(value.get(key)) is type(expected) and value[key] == expected
    return {k: value[k] for k in ('preset_marker', 'input_cents', 'actual_cents',
                                'expected_cents', 'corrected_operator')}


async def run(url, token_env, model, provider, *, timeout=180):
    """Caller must establish target verification and disabled fallback beforehand."""
    require_checks_enabled()
    source = config(model, provider)
    registry = Registry.from_dict(source)
    assert not registry.unavailable_policies
    secret, operator = secrets.token_hex(32), secrets.token_hex(32)
    deployment = {'auth_profiles': {'source': {'scope': 'smoke', 'secret_env': 'ORPHEUS_SMOKE_HMAC'}},
        'targets': {'local': {'url': url, 'token_env': token_env, 'principal': 'isolated-smoke',
            'verified': True, 'fallback_disabled': True, 'allow_loopback_http': True,
            'models': {model: {'provider': provider}}}},
        'operators': {'ORPHEUS_SMOKE_OPERATOR': ['smoke-' + name for name in PRESETS]}}
    host = RecordingRunClient(deployment['targets'])
    # No requested preset/model/options are extracted from the event body.
    raw = json.dumps({'task': TASK, 'preset_id': 'payload-override',
        'model': 'payload-override', 'instructions': 'payload-override',
        'model_options': {'reasoning_effort': 'payload-override'}}).encode()
    headers = {'Content-Type': 'application/json', 'X-Hub-Signature-256':
        'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}
    auth = {'Authorization': 'Bearer ' + operator}
    report = {'scope': 'Signed HTTP ingress, production registry/resolver/client, upstream public Run API',
        'requested_model': model, 'requested_provider': provider, 'cases': []}
    with tempfile.TemporaryDirectory(prefix='orpheus-webhook-smoke-') as directory, patch.dict(
            os.environ, {'ORPHEUS_SMOKE_HMAC': secret, 'ORPHEUS_SMOKE_OPERATOR': operator}):
        ledger = Ledger(Path(directory) / 'ledger.sqlite3')
        service = WebhookService(registry, Resolver(registry), deployment, ledger, host=host)
        app = web.Application()
        service.mount(app)
        async with cancel_unfinished(host), TestClient(TestServer(app, host='127.0.0.1')) as client:
            bad = await client.post('/orpheus/webhooks/reviewer', data=raw,
                headers={'Content-Type': 'application/json'})
            assert bad.status == 401 and host.calls == []
            report['unauthenticated_rejected'] = True
            for name in PRESETS:
                response = await client.post('/orpheus/webhooks/' + name, data=raw, headers=headers)
                assert response.status == 202
                rid = (await response.json())['request_id']
                assert (await client.get('/orpheus/requests/' + rid)).status == 403
                replay = await client.post('/orpheus/webhooks/' + name, data=raw, headers=headers)
                assert replay.status == 200 and (await replay.json())['request_id'] == rid
                deadline = asyncio.get_running_loop().time() + timeout
                while True:
                    status = await client.post('/orpheus/requests/' + rid + '/reconcile', json={}, headers=auth)
                    assert status.status == 200
                    result = await status.json()
                    if result['state'] in ('completed', 'failed', 'cancelled', 'unknown'):
                        break
                    if asyncio.get_running_loop().time() >= deadline:
                        await client.post('/orpheus/requests/' + rid + '/cancel', headers=auth)
                        raise TimeoutError('bounded_probe_timeout')
                    await asyncio.sleep(.5)
                assert result['state'] == 'completed', 'native_run_not_completed'
                selected = result['selection']
                assert selected['preset_id'] == name and selected['model'] == model
                assert selected['provider'] == provider and selected['tuple_id'] == 'review'
                assert len(host.calls) == len(report['cases']) + 1
                call = host.calls[-1]
                configured_instructions = next(p for p in source['presets'] if p['id'] == name)['fields']['instructions']['value']
                assert call['payload'] == {'input': 'event.task: ' + json.dumps(TASK),
                    'model': model, 'provider': provider, 'instructions': configured_instructions}
                assert 'payload-override' not in json.dumps(call['payload'])
                value = finding(result['result'])
                assert value['preset_marker'] == name
                native = host.statuses[result['host_id']]
                report['cases'].append({'route': name, 'preset_id': selected['preset_id'],
                    'tuple_id': selected['tuple_id'], 'request_id': rid, 'host_id': result['host_id'],
                    'session_id': native.get('session_id'), 'state': result['state'],
                    'replay_deduplicated': True, 'payload_overrides_ignored': True,
                    'exact_launch_payload_verified': True, 'finding': value,
                    'observed': result.get('observed')})
            assert len({row['host_id'] for row in report['cases']}) == 2
            sessions = [row['session_id'] for row in report['cases']]
            assert all(isinstance(value, str) and value for value in sessions)
            assert len(set(sessions)) == 2
            report['distinct_run_scoped_session_ids_verified'] = True
            report['upstream_submissions'] = len(host.calls)
            report['passed'] = True
    return report


def main():
    require_checks_enabled()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--token-env', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--provider', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--verified-isolated-target', action='store_true', required=True)
    args = parser.parse_args()
    try:
        report = asyncio.run(run(args.url, args.token_env, args.model, args.provider))
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
        print(json.dumps({'passed': report['passed'], 'cases': len(report['cases'])}))
        return 0
    except Exception as exc:
        # Never print arbitrary upstream response or credential-bearing exceptions.
        print(json.dumps({'passed': False, 'error_type': type(exc).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
