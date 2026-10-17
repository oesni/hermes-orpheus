"""Deterministic HTTP oracle for the opt-in live webhook harness."""
import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

spec = importlib.util.spec_from_file_location('webhook_preset_smoke', Path(__file__).with_name('webhook_preset_smoke.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.mark.parametrize('corrupt_instructions', [False, True])
def test_fixed_route_http_probe(monkeypatch, corrupt_instructions):
    monkeypatch.setenv('TEST_FIXED_HOST_TOKEN', 'test-only-not-a-real-credential')
    if corrupt_instructions:
        original = probe.Resolver.resolve
        async def altered(self, *args, **kwargs):
            result = await original(self, *args, **kwargs)
            result['instructions'] += ' payload-override'
            return result
        monkeypatch.setattr(probe.Resolver, 'resolve', altered)
    async def scenario():
        calls = []
        async def submit(request):
            assert request.headers['Authorization'] == 'Bearer test-only-not-a-real-credential'
            assert request.headers['Idempotency-Key'].startswith('orpheus-')
            calls.append(await request.json())
            return web.json_response({'run_id': str(len(calls))})
        async def status(request):
            index = int(request.match_info['id']) - 1
            value = {'preset_marker': probe.PRESETS[index], 'input_cents': 10000,
                'actual_cents': 10000, 'expected_cents': 9000, 'corrected_operator': '>='}
            return web.json_response({'status': 'completed', 'session_id': 'session-' + str(index),
                'output': json.dumps(value), 'runtime': {'model': 'test-model', 'provider': 'test-provider'}})
        app = web.Application()
        app.router.add_post('/v1/runs', submit)
        app.router.add_get('/v1/runs/{id}', status)
        async with TestServer(app) as server:
            if corrupt_instructions:
                with pytest.raises(AssertionError):
                    await probe.run(str(server.make_url('')).rstrip('/'),
                        'TEST_FIXED_HOST_TOKEN', 'test-model', 'test-provider')
                assert len(calls) == 1
                assert 'payload-override' in calls[0]['instructions']
                return
            report = await probe.run(str(server.make_url('')).rstrip('/'),
                'TEST_FIXED_HOST_TOKEN', 'test-model', 'test-provider')
        assert report['passed'] and report['upstream_submissions'] == 2
        assert all(row['exact_launch_payload_verified'] for row in report['cases'])
        assert all('payload-override' not in json.dumps(call) for call in calls)
    asyncio.run(scenario())


@pytest.mark.parametrize('value', [True, '10000', 9999])
def test_review_oracle_rejects_wrong_boundary_type_and_value(value):
    result = {'preset_marker': 'reviewer', 'input_cents': value, 'actual_cents': 10000,
              'expected_cents': 9000, 'corrected_operator': '>='}
    with pytest.raises(AssertionError):
        probe.finding(json.dumps(result))


@pytest.mark.parametrize('optimization', ['-O', '-OO'])
def test_optimized_execution_refused(optimization):
    path = str(Path(probe.__file__).resolve())
    cli = subprocess.run([sys.executable, optimization, path, '--help'], capture_output=True, text=True)
    assert cli.returncode != 0 and 'optimized_python_disables_verification' in cli.stderr
    code = ('import runpy,asyncio; ns=runpy.run_path(' + repr(path) + '); '
            "asyncio.run(ns['run']('invalid','missing','m','p'))")
    direct = subprocess.run([sys.executable, optimization, '-c', code], capture_output=True, text=True)
    assert direct.returncode != 0 and 'optimized_python_disables_verification' in direct.stderr
