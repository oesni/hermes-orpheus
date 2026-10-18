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
            config = sample()
            config['presets'] = [dict(copy.deepcopy(config['presets'][0]), id=f'p{i}') for i in range(256)]
            config['policies']['interactive']['preset_selector'] = choice(kind, 'p')
            self.assertIn('interactive', Registry.from_dict(config).unavailable_policies)
