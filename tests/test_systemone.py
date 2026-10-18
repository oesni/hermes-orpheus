"""Canonical protocol spelling and compatibility across resolver graph stages."""
import copy
import unittest

from orpheus.config import Registry, digest
from orpheus.resolver import Resolver, SelectionError
from tests.test_config import sample
from tests import test_config


def choice(kind, node_id):
    return {'id': node_id, 'kind': kind, 'model': 'typesafe/jev-1.14',
            'projection_fields': []}


class SystemOneTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_spellings_select_preset_and_tuple_without_mutating_source(self):
        for kind in ('systemone', 'jev'):
            with self.subTest(kind=kind):
                config = sample()
                policy = config['policies']['interactive']
                policy['preset_selector'] = choice(kind, 'p')
                policy['field_resolver'] = choice(kind, 'f')
                original = copy.deepcopy(config)
                registry = Registry.from_dict(config)
                self.assertEqual(registry.source, original)
                self.assertEqual(config, original)
                self.assertEqual(registry.policies['interactive']['revision'], digest(policy))
                for stage in ('preset_selector', 'field_resolver'):
                    self.assertEqual(registry.policies['interactive'][stage]['kind'], 'systemone')
                class Client:
                    async def choose(self, **kwargs):
                        return {'choice': 'analyst' if 'analyst' in kwargs['choices'] else 'deep'}
                result = await Resolver(registry, Client()).resolve('subagent', 'task')
                self.assertEqual(result['effort'], 'high')
                with self.assertRaisesRegex(SelectionError, 'Field proposals forbidden'):
                    await Resolver(registry, Client()).resolve('subagent', 'task', proposals={})

    async def test_mixed_alias_fallback_node_and_invalid_response(self):
        for root_kind, fallback_kind in (('systemone', 'jev'), ('jev', 'systemone')):
            with self.subTest(root_kind=root_kind):
                config = sample()
                policy = config['policies']['interactive']
                policy['field_resolver'] = dict(choice(root_kind, 'f'), on_error=[
                    {'id': 'invalid', 'errors': ['invalid_response'], 'target': 'retry'}])
                policy['resolver_nodes'] = {'retry': choice(fallback_kind, 'retry')}
                registry = Registry.from_dict(config)
                self.assertEqual(registry.policies['interactive']['resolver_nodes']['retry']['kind'], 'systemone')
                class Client:
                    count = 0
                    async def choose(self, **kwargs):
                        self.count += 1
                        return {'choice': 'outside' if self.count == 1 else 'quick'}
                result = await Resolver(registry, Client()).resolve('subagent', 'task', preset_id='analyst')
                self.assertEqual(result['effort'], 'low')
                self.assertTrue(any(a.get('cause') == 'invalid_response' for a in result['attempts']))

    async def test_webhook_both_spellings(self):
        for kind in ('systemone', 'jev'):
            with self.subTest(kind=kind):
                config = test_config.ConfigTests().webhook_config()
                policy = config['policies']['incoming']
                policy['preset_selector'] = choice(kind, 'p')
                policy['field_resolver'] = choice(kind, 'f')
                class Client:
                    async def choose(self, **kwargs):
                        return {'choice': 'analyst' if 'analyst' in kwargs['choices'] else 'quick'}
                result = await Resolver(Registry.from_dict(config), Client()).resolve(
                    'webhook', 'task', context={'event.title': 'review'}, route_id='issue')
                self.assertEqual(result['effort'], 'low')

    def test_invalid_kind_and_constraints_quarantine(self):
        for kind in ('systemone', 'jev'):
            for change in ({'model': ''}, {'projection_fields': ['context.unknown']},
                           {'timeout': 0}, {'retries': 4}, {'kind': 'system_one'},
                           {'kind': ['systemone']}):
                with self.subTest(kind=kind, change=change):
                    config = sample()
                    config['policies']['interactive']['field_resolver'] = dict(choice(kind, 'f'), **change)
                    self.assertIn('interactive', Registry.from_dict(config).unavailable_policies)

    def test_choice_limit_for_both_spellings(self):
        for kind in ('systemone', 'jev'):
            for count in (255, 256):
                config = sample()
                config['presets'] = [dict(copy.deepcopy(config['presets'][0]), id=f'p{i}') for i in range(count)]
                config['policies']['interactive']['preset_selector'] = choice(kind, 'p')
                registry = Registry.from_dict(config)
                if count == 255:
                    self.assertIn('interactive', registry.policies)
                else:
                    self.assertEqual(registry.unavailable_policies['interactive'],
                                     'System One supports at most 255 choices')

    def test_canonical_example(self):
        from pathlib import Path
        from orpheus.deployment import validate_routes
        import yaml
        root = Path(__file__).resolve().parents[1]
        registry = Registry.from_yaml((root / 'examples/systemone-presets.yaml').read_text())
        validate_routes(registry, yaml.safe_load((root / 'examples/deployment.yaml').read_text()))
        self.assertFalse(registry.unavailable_policies)
        self.assertFalse(registry.quarantined)


class SystemOneDeploymentTests(unittest.TestCase):
    def test_canonical_legacy_and_mixed_settings(self):
        from orpheus.deployment import systemone_settings, validate_deployment
        endpoint = 'https://systemone.example/choice'
        for endpoint_key in ('systemone_endpoint', 'jev_endpoint'):
            for token_key in ('systemone_token_env', 'jev_token_env'):
                settings = {endpoint_key: endpoint, token_key: 'CUSTOM_KEY'}
                validate_deployment(settings)
                self.assertEqual(systemone_settings(settings), (endpoint, 'CUSTOM_KEY'))
        settings = {'systemone_endpoint': endpoint, 'jev_endpoint': endpoint,
                    'systemone_token_env': 'CUSTOM_KEY', 'jev_token_env': 'CUSTOM_KEY'}
        validate_deployment(settings)
        self.assertEqual(systemone_settings(settings), (endpoint, 'CUSTOM_KEY'))

    def test_conflicts_and_invalid_bindings_reject_without_values(self):
        from orpheus.deployment import DeploymentError, validate_deployment
        for settings in (
            {'systemone_endpoint': 'https://one.example', 'jev_endpoint': 'https://two.example'},
            {'systemone_token_env': 'PRIVATE_A', 'jev_token_env': 'PRIVATE_B'},
            {'systemone_endpoint': 'https://one.example'},
            {'systemone_endpoint': 'https://one.example', 'jev_token_env': ''},
            {'systemone_endpoint': 'http://one.example', 'systemone_token_env': 'KEY'},
        ):
            with self.subTest(settings=settings), self.assertRaises(DeploymentError) as error:
                validate_deployment(settings)
            for value in settings.values():
                if value:
                    self.assertNotIn(value, str(error.exception))

    def test_python_compatibility_aliases_and_client_conflicts(self):
        from orpheus.systemone import SystemOneClient
        from orpheus.jev import JevClient
        from orpheus.deployment import (DEFAULT_SYSTEMONE_ENDPOINT, DEFAULT_JEV_ENDPOINT,
                                        validate_systemone_endpoint, validate_jev_endpoint)
        self.assertIs(SystemOneClient, JevClient)
        self.assertEqual(DEFAULT_SYSTEMONE_ENDPOINT, DEFAULT_JEV_ENDPOINT)
        self.assertIs(validate_systemone_endpoint, validate_jev_endpoint)
        client = object()
        resolver = Resolver(Registry.from_dict(sample()), jev_client=client)
        self.assertIs(resolver.systemone_client, client)
        self.assertIs(resolver.jev_client, client)
        resolver.jev_client = None
        self.assertIsNone(resolver.systemone_client)
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            Resolver(Registry.from_dict(sample()), systemone_client=object(), jev_client=object())
