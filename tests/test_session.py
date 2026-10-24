"""Host-observed calling-session model: hook capture, discovery and selection inputs."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
import yaml
from orpheus.config import Registry, ConfigError
from orpheus.plugin import register
from orpheus.resolver import Resolver, SelectionError
from orpheus.session import SessionModels, describe, selection_inputs
from tests.test_config import sample
from tests.test_plugin import Context


INVENTORY = {'opus': {'provider': 'claude', 'model': 'opus-5'}, 'sol': {'provider': 'codex', 'model': 'sol-6'}}
SESSION_SCHEMA = {'session.model_ref': {'type': 'string', 'max_length': 64, 'trust': 'verified_metadata'},
                  'session.model': {'type': 'string', 'max_length': 128, 'trust': 'verified_metadata'}}


def two_model_config():
    """Single preset whose two tuples differ only by model; parent picks the preset, rules pick the tuple."""
    return {'schema_version': 1, 'inventory': {'models': copy.deepcopy(INVENTORY)},
            'presets': [{'id': 'reviewer', 'fields': {'model': {'mode': 'enum', 'candidates': ['opus', 'sol']}},
                         'compatible_settings': {'opus': {'model': 'opus'}, 'sol': {'model': 'sol'}}}],
            'subagent_policy': 'interactive',
            'policies': {'interactive': {
                'entrypoint': 'subagent',
                'input_schema': {'task.text': {'type': 'string', 'max_length': 100, 'required': True, 'trust': 'payload'},
                                 **copy.deepcopy(SESSION_SCHEMA)},
                'preset_selector': {'id': 'p', 'kind': 'parent'},
                'field_resolver': {'id': 'f', 'kind': 'rules',
                                   'rules': [{'id': 'other-than-opus', 'priority': 1,
                                              'when': {'field': 'session.model_ref', 'op': 'eq', 'value': 'opus'},
                                              'settings': 'sol'}],
                                   'no_match': {'kind': 'fixed', 'settings': 'opus'}}}}}


def entry_of(models, session_id):
    entry = models.get(session_id)
    assert entry is not None, session_id
    return entry


class SessionModelsTests(unittest.TestCase):
    def test_latest_observation_per_session_and_incomplete_payloads_ignored(self):
        clock = iter(range(100)).__next__
        models = SessionModels(clock=clock)
        self.assertIsNone(models.observe(session_id='a', model='opus-5', provider='claude', api_call_count=1))
        models.observe(session_id='a', model='sol-6', provider='codex')
        bad_payloads: list[dict] = [{'session_id': '', 'model': 'm', 'provider': 'p'}, {'session_id': 'b', 'model': None, 'provider': 'p'},
                                    {'session_id': 'b', 'model': 'm', 'provider': ''}, {'session_id': 7, 'model': 'm', 'provider': 'p'}]
        for bad in bad_payloads:
            models.observe(**bad)
        self.assertEqual(models.get('a'), {'model': 'sol-6', 'provider': 'codex', 'observed_at': 1})
        self.assertIsNone(models.get('b'))
        self.assertIsNone(models.get(None))
        self.assertIsNone(models.get(''))

    def test_latest_delivery_wins_and_payload_timestamps_are_ignored(self):
        """Wall-clock payload fields can repeat or move backwards, so they never order deliveries."""
        models = SessionModels(clock=iter([10.0, 11.0, 12.0]).__next__)
        models.observe(session_id='s', model='first', provider='p', ended_at=105.0, started_at=100.0)
        models.observe(session_id='s', model='second', provider='p', ended_at=100.0)
        self.assertEqual(entry_of(models, 's'), {'model': 'second', 'provider': 'p', 'observed_at': 11.0})
        models.observe(session_id='s', model='third', provider='p', ended_at=100.0)
        self.assertEqual(entry_of(models, 's')['model'], 'third')

    def test_eviction_is_by_observation_recency_not_reads(self):
        models = SessionModels(limit=2)
        models.observe(session_id='a', model='m', provider='p')
        models.observe(session_id='b', model='m', provider='p')
        models.get('a')
        models.observe(session_id='c', model='m', provider='p')
        self.assertIsNone(models.get('a'))
        self.assertIsNotNone(models.get('b'))
        models.observe(session_id='b', model='m2', provider='p')
        models.observe(session_id='d', model='m', provider='p')
        self.assertIsNone(models.get('c'))
        self.assertEqual(entry_of(models, 'b')['model'], 'm2')

    def test_bounded_and_returned_copies(self):
        models = SessionModels(limit=2)
        for sid in ('a', 'b', 'c'):
            models.observe(session_id=sid, model='m', provider='p')
        self.assertIsNone(models.get('a'))
        entry = models.get('c')
        assert entry is not None
        entry['model'] = 'tampered'
        self.assertEqual(models.get('c'), {**entry, 'model': 'm'})
        invalid_limits: list = [0, -1, 1.5, True]
        for limit in invalid_limits:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                SessionModels(limit=limit)

    def test_concurrent_observations_stay_consistent(self):
        models = SessionModels(limit=64)
        def worker(n):
            for i in range(200):
                models.observe(session_id=f's{i % 80}', model=f'm{n}', provider='p')
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertLessEqual(len(models._entries), 64)

    def test_describe_maps_exact_inventory_pair_only(self):
        entry = {'model': 'opus-5', 'provider': 'claude', 'observed_at': 1.0}
        def described(value, inventory):
            result = describe(value, inventory)
            assert result is not None
            return result
        self.assertEqual(described(entry, INVENTORY)['model_ref'], 'opus')
        self.assertIsNone(described({**entry, 'provider': 'other'}, INVENTORY)['model_ref'])
        ambiguous = described(entry, {**INVENTORY, 'opus-alias': {'provider': 'claude', 'model': 'opus-5'}})
        self.assertIsNone(ambiguous['model_ref'])
        self.assertEqual(ambiguous['matching_refs'], ['opus', 'opus-alias'])
        self.assertIsNone(describe(None, INVENTORY))
        self.assertEqual(selection_inputs(None), {})
        self.assertEqual(selection_inputs(describe({**entry, 'provider': 'other'}, INVENTORY)),
                         {'session.model': 'opus-5', 'session.provider': 'other'})


class SessionSchemaTests(unittest.TestCase):
    def schema(self, spec, name='session.model_ref', webhook=False):
        config = two_model_config()
        config['policies']['interactive']['input_schema'][name] = spec
        return Registry.from_dict(config)

    def test_only_optional_verified_metadata_strings(self):
        ok = self.schema({'type': 'string', 'trust': 'verified_metadata', 'required': False})
        self.assertIn('interactive', ok.policies)
        for spec in ({'type': 'string'}, {'type': 'string', 'trust': 'payload'},
                     {'type': 'string', 'trust': 'verified_metadata', 'required': True},
                     {'type': 'boolean', 'trust': 'verified_metadata'}):
            with self.subTest(spec=spec):
                self.assertIn('interactive', self.schema(spec).unavailable_policies)

    def test_other_verified_metadata_and_unknown_session_names_still_rejected(self):
        for name in ('context.model', 'session.other', 'session'):
            with self.subTest(name=name):
                self.assertIn('interactive', self.schema({'type': 'string', 'trust': 'verified_metadata'}, name).unavailable_policies)

    def test_webhook_event_schema_cannot_declare_session_fields(self):
        from orpheus.config import input_schema
        with self.assertRaises(ConfigError):
            input_schema({'session.model': {'type': 'string', 'source': 'body', 'pointer': '/m'}}, webhook=True)


class SessionResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_rules_route_on_host_session_model(self):
        resolver = Resolver(Registry.from_dict(two_model_config()))
        chosen = await resolver.resolve('subagent', 'review', preset_id='reviewer', session={'session.model_ref': 'opus'})
        self.assertEqual(chosen['tuple_id'], 'sol')
        self.assertEqual(chosen['session_inputs'], {'session.model_ref': 'opus'})
        unknown = await resolver.resolve('subagent', 'review', preset_id='reviewer')
        self.assertEqual(unknown['tuple_id'], 'opus')
        self.assertEqual(unknown['session_inputs'], {})

    async def test_caller_context_cannot_supply_session_values(self):
        resolver = Resolver(Registry.from_dict(two_model_config()))
        for context in ({'session.model_ref': 'opus'}, {'model_ref': 'opus'}):
            with self.subTest(context=context), self.assertRaises(SelectionError):
                await resolver.resolve('subagent', 'review', context=context, preset_id='reviewer')

    async def test_undeclared_or_invalid_session_values_are_omitted(self):
        config = two_model_config()
        config['policies']['interactive']['input_schema'].pop('session.model')
        config['policies']['interactive']['input_schema']['session.model_ref']['max_length'] = 4
        resolver = Resolver(Registry.from_dict(config))
        chosen = await resolver.resolve('subagent', 'review', preset_id='reviewer',
                                        session={'session.model': 'opus-5', 'session.model_ref': 'too-long-ref',
                                                 'context.x': 'ignored'})
        self.assertEqual(chosen['session_inputs'], {})
        self.assertEqual(chosen['tuple_id'], 'opus')

    async def test_systemone_projection_receives_declared_session_value(self):
        config = two_model_config()
        config['policies']['interactive']['field_resolver'] = {'id': 'f', 'kind': 'systemone', 'model': 'jev',
                                                               'projection_fields': ['task.text', 'session.model_ref']}
        class Fake:
            async def choose(self, **kwargs):
                self.state = kwargs['state']; return {'choice': 'sol'}
        fake = Fake()
        await Resolver(Registry.from_dict(config), fake).resolve('subagent', 'review', preset_id='reviewer',
                                                                  session={'session.model_ref': 'opus', 'session.model': 'opus-5'})
        self.assertEqual(fake.state, {'session.model_ref': 'opus', 'task.text': 'review'})

    async def test_existing_policies_without_session_fields_are_unchanged(self):
        result = await Resolver(Registry.from_dict(sample())).resolve('subagent', 'analyze', preset_id='analyst',
                                                                      proposals={'effort': 'high'},
                                                                      session={'session.model': 'x'})
        self.assertEqual(result['resolved'], {'model': 'm', 'provider': 'p', 'effort': 'high'})
        self.assertEqual(result['session_inputs'], {})


class HookContext(Context):
    def __init__(self, directory):
        super().__init__(directory)
        self.hooks = {}
    def register_hook(self, name, callback): self.hooks.setdefault(name, []).append(callback)


class SessionPluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ctx = HookContext(self.directory.name)
        self.addCleanup(lambda: [fn() for fn in self.ctx.cleanups])
        root = Path(self.directory.name)
        (root / 'presets.yaml').write_text(yaml.safe_dump(two_model_config()))
        (root / 'deployment.yaml').write_text(yaml.safe_dump({'subagent': {'fallback_disabled': True, 'verified_settings': [
            {'provider': 'claude', 'model': 'opus-5'}, {'provider': 'codex', 'model': 'sol-6'}]}}))
        self.ctx.config.update(config_path=str(root / 'presets.yaml'), deployment_path=str(root / 'deployment.yaml'))
        register(self.ctx)

    async def tool(self, name, args, **kwargs):
        return json.loads(await self.ctx.tools[name]['handler'](args, **kwargs))

    async def test_registers_post_api_request_observer(self):
        self.assertEqual(set(self.ctx.hooks), {'post_api_request'})

    async def test_presets_report_calling_session_model(self):
        self.assertIsNone((await self.tool('orpheus_presets', {}, session_id='s1'))['session'])
        self.ctx.hooks['post_api_request'][0](session_id='s1', model='opus-5', provider='claude', response={})
        self.ctx.hooks['post_api_request'][0](session_id='s2', model='sol-6', provider='codex')
        session = (await self.tool('orpheus_presets', {}, session_id='s1'))['session']
        self.assertEqual((session['provider'], session['model'], session['model_ref']), ('claude', 'opus-5', 'opus'))
        self.assertIsNone((await self.tool('orpheus_presets', {}))['session'])

    async def test_spawn_routes_on_observed_session_and_records_it(self):
        self.ctx.hooks['post_api_request'][0](session_id='s1', model='opus-5', provider='claude')
        result = await self.tool('orpheus_spawn', {'task': 'review', 'preset_id': 'reviewer'}, session_id='s1')
        self.assertEqual(result['state'], 'running')
        self.assertEqual(self.ctx.subagent_lifecycle.calls[-1]['model'], 'sol-6')
        other = await self.tool('orpheus_spawn', {'task': 'review', 'preset_id': 'reviewer'}, session_id='unseen')
        self.assertEqual(other['state'], 'running')
        self.assertEqual(self.ctx.subagent_lifecycle.calls[-1]['model'], 'opus-5')

    async def test_spawn_schema_unchanged(self):
        schema = self.ctx.tools['orpheus_spawn']['schema']['parameters']
        self.assertEqual(set(schema['properties']), {'task', 'context', 'preset_id', 'proposals'})
        rejected = await self.tool('orpheus_spawn', {'task': 'review', 'preset_id': 'reviewer', 'session': {}}, session_id='s1')
        self.assertIn('error', rejected)
