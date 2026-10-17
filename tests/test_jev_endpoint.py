import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiohttp
import yaml

from orpheus.deployment import DEFAULT_JEV_ENDPOINT, DeploymentError, validate_deployment
from orpheus.jev import JevClient
from orpheus.plugin import register
from orpheus.resolver import SelectionError
from tests.test_plugin import Context


class EndpointTests(unittest.TestCase):
    def test_secure_custom_endpoint_and_default(self):
        validate_deployment({})
        endpoint = 'https://systemone.example:8443/custom/predict'
        validate_deployment({'jev_endpoint': endpoint, 'jev_token_env': 'CUSTOM_JEV_KEY'})
        self.assertEqual(JevClient('test').endpoint, DEFAULT_JEV_ENDPOINT)
        self.assertEqual(JevClient('test', endpoint=endpoint).endpoint, endpoint)

    def test_endpoint_requires_explicit_credential_binding(self):
        with self.assertRaisesRegex(DeploymentError, 'jev_endpoint_requires_token_env'):
            validate_deployment({'jev_endpoint': 'https://systemone.example/custom'})
        # Legacy token variable overrides retain the original Typesafe endpoint.
        validate_deployment({'jev_token_env': 'CUSTOM_TYPESAFE_KEY'})
        validate_deployment({'jev_endpoint': DEFAULT_JEV_ENDPOINT})

    def test_invalid_endpoint_rejected_without_value_in_error(self):
        for endpoint in (None, 42, '', 'http://localhost/test', 'http://example.com',
                         '//example.com', 'https:///missing', 'https://user:secret@example.com',
                         'https://example.com?token=secret', 'https://example.com#secret',
                         'https://example.com?', 'https://example.com#',
                         ' https://example.com', 'https://exam\nple.com',
                         'https://example.com:99999', 'https://example.com:bad',
                         'https://example.com:0', 'https://example.com\\evil',
                         'https://[invalid'):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(DeploymentError) as error:
                    validate_deployment({'jev_endpoint': endpoint})
                self.assertEqual(str(error.exception), 'invalid_jev_endpoint')
                with self.assertRaises(DeploymentError):
                    JevClient('test', endpoint=endpoint)

    def test_plugin_wires_operator_endpoint_and_credential_env(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = Context(directory)
            deployment = Path(directory) / 'deployment.yaml'
            endpoint = 'https://systemone.example/custom'
            deployment.write_text(yaml.safe_dump({'jev_endpoint': endpoint, 'jev_token_env': 'TEST_JEV_KEY'}))
            ctx.config['deployment_path'] = str(deployment)
            with patch.dict('os.environ', {'TEST_JEV_KEY': 'test-only-key'}, clear=True), patch('orpheus.plugin.JevClient') as client:
                register(ctx)
                client.assert_called_once_with('test-only-key', endpoint=endpoint)
            for close in ctx.cleanups:
                close()


class FakeResponse:
    def __init__(self, status=200):
        self.status = status
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def read(self, limit):
        return json.dumps({'answers': {'selection': {'type': 'choice', 'choice': 'a',
                          'probabilities': {'a': 1}, 'confidence': 1}}}).encode()


class FakeSession:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def post(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        return FakeResponse(self.status)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_custom_endpoint_model_and_auth_are_used_without_redirects(self):
        session = FakeSession()
        endpoint = 'https://systemone.example/custom'
        result = await JevClient('test-key', session, endpoint=endpoint).choose(
            model='typesafe/jev-1.14', state={'task': 'review'}, choices={'a': 'review code'}, timeout=3)
        self.assertEqual(result['choice'], 'a')
        self.assertEqual(len(session.calls), 1)
        url, kwargs = session.calls[0]
        self.assertEqual(url, endpoint)
        self.assertEqual(kwargs['headers'], {'Authorization': 'Bearer test-key'})
        self.assertEqual(kwargs['json']['model'], 'typesafe/jev-1.14')
        self.assertEqual(kwargs['json']['state'], {'task': 'review'})
        self.assertIs(kwargs['allow_redirects'], False)
        self.assertEqual(kwargs['timeout'].total, 3)

    async def test_redirect_response_fails_without_retry(self):
        session = FakeSession(307)
        with self.assertRaises(SelectionError) as error:
            await JevClient('test-key', session).choose(model='typesafe/jev-1.14', state={}, choices={'a': 'a'})
        self.assertEqual(error.exception.code, 'invalid_response')
        self.assertEqual(len(session.calls), 1)

    async def test_transport_error_has_no_credential_or_endpoint_in_message(self):
        session = FakeSession()
        with patch.object(session, 'post', side_effect=aiohttp.ClientError('private transport details')):
            with self.assertRaises(SelectionError) as error:
                await JevClient('test-key', session).choose(model='typesafe/jev-1.14', state={}, choices={'a': 'a'})
        self.assertEqual(str(error.exception), 'Jev transport unavailable')
