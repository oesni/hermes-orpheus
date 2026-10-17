import copy
import unittest
from orpheus.config import Registry, ConfigError


def sample():
    return {'schema_version':1,'inventory':{'models':{'small':{'provider':'p','model':'m','efforts':['low','high']}}},'presets':[{'id':'analyst','fields':{'model':{'mode':'fixed','value':'small'},'effort':{'mode':'enum','candidates':['low','high']}},'compatible_settings':{'quick':{'effort':'low'},'deep':{'effort':'high'}}}], 'subagent_policy':'interactive','policies':{'interactive':{'entrypoint':'subagent','input_schema':{'task.text':{'type':'string','max_length':100,'required':True,'trust':'payload'},'context.kind':{'type':'string','max_length':32,'required':False,'trust':'payload'}},'preset_selector':{'id':'p','kind':'parent'},'field_resolver':{'id':'f','kind':'parent'}}}}


class ConfigTests(unittest.TestCase):
    def test_duplicate_yaml(self):
        with self.assertRaises(ConfigError): Registry.from_yaml('schema_version: 1\nschema_version: 1')
    def test_independent_quarantine(self):
        config=sample(); config['presets'].append({'id':'bad','fields':{}})
        registry=Registry.from_dict(config)
        self.assertIn('analyst',registry.presets); self.assertIn('bad',registry.quarantined)
    def test_duplicate_quarantines_all(self):
        config=sample(); config['presets']*=2
        registry=Registry.from_dict(config)
        self.assertEqual(registry.presets,{})
    def test_invalid_update_drops_old(self):
        config=sample(); old=Registry.from_dict(config)
        config['presets'][0]['fields']['effort']['mode']='free'
        new=Registry.from_dict(config)
        self.assertNotEqual(old.revision,new.revision); self.assertNotIn('analyst',new.presets)
    def test_source_failure_freezes(self):
        registry=Registry.from_dict(sample())
        with self.assertRaises(ConfigError): registry.refresh_yaml('[')
        self.assertFalse(registry.admissions_enabled)
    def test_webhook_parent_forbidden(self):
        config=sample(); config['policies']['interactive']['entrypoint']='webhook'
        with self.assertRaises(ConfigError): Registry.from_dict(config)
    def test_cross_preset_rule_validation(self):
        config=sample(); other=copy.deepcopy(config['presets'][0]); other['id']='other'; del other['compatible_settings']['deep']; config['presets'].append(other)
        config['policies']['interactive']['field_resolver']={'id':'f','kind':'fixed','settings':'deep'}
        self.assertIn('interactive',Registry.from_dict(config).unavailable_policies)
    def test_model_effort_compatibility(self):
        config=sample(); config['inventory']['models']['small']['efforts']=['low']
        self.assertIn('analyst',Registry.from_dict(config).quarantined)
    def test_fallback_cycle(self):
        config=sample(); p=config['policies']['interactive']; p['field_resolver']={'id':'f','kind':'rules','rules':[],'no_match':{'kind':'resolver','target':'again'}}; p['resolver_nodes']={'again':{'id':'again','kind':'rules','rules':[],'no_match':{'kind':'resolver','target':'again'}}}
        self.assertIn('interactive',Registry.from_dict(config).unavailable_policies)

    def test_malformed_policy_containers_quarantine(self):
        changes=[{'input_schema':['task.text']},{'input_schema':{'task.text':3}}, {'preset_selector':[]}, {'resolver_nodes':[]}, {'field_resolver':{'id':'f','kind':'rules','rules':[],'no_match':[]}}, {'field_resolver':{'id':'f','kind':'rules'}}]
        for change in changes:
            with self.subTest(change=change):
                config=sample(); config['policies']['interactive'].update(change)
                self.assertIn('interactive',Registry.from_dict(config).unavailable_policies)

    def test_invalid_schema_bounds_and_flags(self):
        for change in ({'max_length':True},{'max_length':0},{'max_length':[]},{'required':'true'},{'max_items':10},{'values':['a']},{'trust':'verified_metadata'}):
            with self.subTest(change=change):
                config=sample(); config['policies']['interactive']['input_schema']['task.text'].update(change)
                self.assertIn('interactive',Registry.from_dict(config).unavailable_policies)

    def test_kind_specific_keys_rejected(self):
        for change in ({'settings':'quick'}, {'rules':[]}, {'model':'jev'}):
            config=sample(); config['policies']['interactive']['field_resolver'].update(change)
            self.assertIn('interactive',Registry.from_dict(config).unavailable_policies)

    def test_invalid_preset_guidance_quarantined(self):
        config=sample(); config['presets'][0]['guidance']=[]
        self.assertIn('analyst',Registry.from_dict(config).quarantined)

    def webhook_config(self):
        config=sample(); config['policies']={'incoming':{'entrypoint':'webhook','preset_selector':{'id':'p','kind':'fixed','preset':'analyst'},'field_resolver':{'id':'f','kind':'fixed','settings':'quick'}}}
        config.pop('subagent_policy',None)
        config['webhooks']=[{'id':'issue','policy':'incoming','auth_profile':'auth','execution_target':'api','receipt':{'kind':'disabled'},'event_schema':{'event.title':{'type':'string','source':'body','pointer':'/title','max_length':64}},'routing_fields':['event.title'],'task_fields':['event.title']}]
        return config

    def test_invalid_route_configuration_rejected(self):
        for field in ('auth_profile','execution_target','receipt'):
            config=self.webhook_config(); del config['webhooks'][0][field]
            with self.assertRaises(ConfigError): Registry.from_dict(config)
        for field,value in (('event_schema',3),('routing_fields','event.title'),('task_fields',[[]]),('path','/other'),('event_schema',{'event.title':[]})):
            config=self.webhook_config(); config['webhooks'][0][field]=value
            with self.assertRaises(ConfigError): Registry.from_dict(config)

    def test_shared_route_schema_conflict(self):
        config=self.webhook_config(); route=copy.deepcopy(config['webhooks'][0]); route['id']='other'; route['event_schema']['event.title']['max_length']=128; config['webhooks'].append(route)
        self.assertEqual(set(Registry.from_dict(config).unavailable_routes),{'issue','other'})

    def test_empty_rules_explicit_no_match_allowed(self):
        config=sample(); config['policies']['interactive']['field_resolver']={'id':'f','kind':'rules','rules':[],'no_match':{'kind':'fixed','settings':'quick'}}
        self.assertIn('interactive',Registry.from_dict(config).policies)

    def test_unsupported_webhook_extraction_rejected_at_load(self):
        for change in ({'source':'header','header':'X-Event'}, {'trust':'verified_metadata'}):
            config=self.webhook_config(); config['webhooks'][0]['event_schema']['event.title'].update(change)
            with self.assertRaises(ConfigError): Registry.from_dict(config)

    def test_route_policy_binding_rejected(self):
        for change in ('missing','wrong_entrypoint'):
            config=self.webhook_config()
            if change=='missing': config['webhooks'][0]['policy']='missing'
            elif change=='wrong_entrypoint':
                config['policies']['incoming']=sample()['policies']['interactive']
            with self.assertRaises(ConfigError): Registry.from_dict(config)

    def test_subagent_binding_rejected(self):
        config=sample(); config['subagent_policy']='missing'
        with self.assertRaises(ConfigError): Registry.from_dict(config)
        config=self.webhook_config(); config['subagent_policy']='incoming'
        with self.assertRaises(ConfigError): Registry.from_dict(config)

    def test_task_only_fields_forbidden_in_rules_and_filters(self):
        for location in ('rule','filter'):
            config=self.webhook_config(); route=config['webhooks'][0]; route['routing_fields']=[]
            predicate={'field':'event.title','op':'eq','value':'complex'}
            if location=='rule': config['policies']['incoming']['field_resolver']={'id':'f','kind':'rules','rules':[{'id':'r','priority':1,'when':predicate,'settings':'deep'}]}
            else: route['filters']=predicate
            if location=='filter':
                with self.assertRaises(ConfigError): Registry.from_dict(config)
            else: self.assertIn('issue',Registry.from_dict(config).unavailable_routes)

    def test_shared_routes_require_routing_permission_in_each_route(self):
        config=self.webhook_config(); other=copy.deepcopy(config['webhooks'][0]); other['id']='other'; other['routing_fields']=[]; config['webhooks'].append(other)
        config['policies']['incoming']['field_resolver']={'id':'f','kind':'rules','rules':[{'id':'r','priority':1,'when':{'field':'event.title','op':'exists'},'settings':'deep'}]}
        self.assertEqual(set(Registry.from_dict(config).unavailable_routes),{'issue','other'})

    def test_cli_validate_errors_are_nonzero(self):
        import contextlib
        import io
        import tempfile
        from pathlib import Path
        import yaml
        from orpheus.cli import main
        configs=[]
        malformed=sample(); malformed['policies']['interactive']['input_schema']=['task.text']; configs.append(malformed)
        quarantine=sample(); quarantine['presets'][0]['guidance']=[]; configs.append(quarantine)
        unknown=self.webhook_config(); unknown['webhooks'][0]['policy']='missing'; configs.append(unknown)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.yaml'
            for config in configs:
                path.write_text(yaml.safe_dump(config))
                with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(main(['validate',str(path)]),1)

    def test_webhook_task_fields_must_be_nonempty(self):
        config=self.webhook_config(); config['webhooks'][0]['task_fields']=[]
        with self.assertRaises(ConfigError): Registry.from_dict(config)

    def test_optional_task_field_is_valid_configuration(self):
        config=self.webhook_config(); config['webhooks'][0]['event_schema']['event.title']['required']=False
        self.assertIn('issue',Registry.from_dict(config).webhooks)

    def test_invalid_webhook_preset_isolated_from_valid_native_and_route(self):
        config=self.webhook_config()
        config['policies']['interactive']=sample()['policies']['interactive']
        config['subagent_policy']='interactive'
        broken=copy.deepcopy(config['presets'][0]); broken['id']='broken'; broken['fields']['effort']['candidates']=[]
        config['presets'].append(broken)
        config['policies']['broken-policy']=copy.deepcopy(config['policies']['incoming'])
        config['policies']['broken-policy']['preset_selector']['preset']='broken'
        route=copy.deepcopy(config['webhooks'][0]); route['id']='broken-route'; route['policy']='broken-policy'; config['webhooks'].append(route)
        registry=Registry.from_dict(config)
        self.assertTrue(registry.admissions_enabled)
        self.assertIn('analyst',registry.presets)
        self.assertIn('broken',registry.quarantined)
        self.assertIn('interactive',registry.policies)
        self.assertIn('incoming',registry.policies)
        self.assertEqual(set(registry.unavailable_routes),{'broken-route'})
        self.assertEqual(registry.discover('webhook')['unavailable_routes'],registry.unavailable_routes)
        import yaml
        refreshed=registry.refresh_yaml(yaml.safe_dump(config))
        self.assertTrue(refreshed.admissions_enabled)

    def test_malformed_known_policy_quarantines_only_bound_route(self):
        config=self.webhook_config()
        config['policies']['incoming']['field_resolver']=[]
        registry=Registry.from_dict(config)
        self.assertIn('incoming',registry.unavailable_policies)
        self.assertIn('issue',registry.unavailable_routes)
        self.assertTrue(registry.admissions_enabled)
