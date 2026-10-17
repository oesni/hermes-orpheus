import asyncio
import importlib.metadata
import json
import tempfile
import unittest
from pathlib import Path
from orpheus.plugin import register
from orpheus.cli import main
from tests.test_host import Lifecycle


class Context:
    def __init__(self,directory):
        self.subagent_lifecycle=Lifecycle()
        self.config={'state_dir':directory}
        self.tools={}
        self.cleanups=[]
        self.platforms={}
    def get_config(self,key,default=None): return self.config.get(key,default)
    def register_tool(self,**kw): self.tools[kw['name']]=kw
    def on_unload(self,callback): self.cleanups.append(callback)
    def register_platform_handler(self,name,factory): self.platforms[name]=factory


class PluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ctx=Context(self.directory.name)
        self.addCleanup(lambda:[fn() for fn in self.ctx.cleanups])
    async def test_installed_entrypoint_is_loadable(self):
        entries=importlib.metadata.entry_points(group='hermes_agent.plugins')
        entry=next(e for e in entries if e.name=='hermes-orpheus')
        self.assertIs(entry.load(),register)
    async def test_empty_registry_discovery_and_four_tools(self):
        register(self.ctx)
        self.assertEqual(set(self.ctx.tools),{'orpheus_presets','orpheus_spawn','orpheus_status','orpheus_cancel'})
        result=json.loads(await self.ctx.tools['orpheus_presets']['handler']({}))
        self.assertEqual(result['presets'],[])
        self.assertIn('Configure',result['guidance'])
    async def test_unconfigured_spawn_rejected_without_host_call(self):
        register(self.ctx)
        result=json.loads(await self.ctx.tools['orpheus_spawn']['handler']({'task':'test','preset_id':'absent'}))
        self.assertIn('error',result)
        self.assertEqual(self.ctx.subagent_lifecycle.calls,[])
    async def test_original_example_loads_and_reports_effort_gate(self):
        self.ctx.config['config_path']=str(Path(__file__).parents[1]/'examples/presets.yaml')
        register(self.ctx)
        result=json.loads(await self.ctx.tools['orpheus_presets']['handler']({}))
        self.assertIn('unsupported_effort',result['presets'][0]['capability_reasons'])

class DeploymentValidationTests(unittest.TestCase):
    def test_strict_deployment_rejects_typoes_and_scope_substrings(self):
        from orpheus.deployment import validate_deployment
        for config in ({'redact_literal':['secret']}, {'operators':{'TOKEN':'long-scope'}}, {'operators':{'TOKEN':[42]}}, {'subagent':{'verified_settings':'anything'}}, {'subagent':{'verified_settings':[{'provider':'p','model':42}]}}, {'subagent':{'redact_literals':['misplaced']}}):
            with self.subTest(config=config), self.assertRaises(ValueError): validate_deployment(config)
        validate_deployment({'redact_literals':['secret'],'operators':{'TOKEN':['exact-scope']},'subagent':{'verified_settings':[{'provider':'p','model':'m','effort':'high'}]}})

    def test_plugin_passes_global_redaction_to_native_adapter(self):
        from unittest.mock import patch
        import yaml
        with tempfile.TemporaryDirectory() as directory:
            ctx=Context(directory)
            path=Path(directory)/'deployment.yaml'
            path.write_text(yaml.safe_dump({'redact_literals':['secret']}))
            ctx.config['deployment_path']=str(path)
            with patch('orpheus.plugin.SubagentAdapter') as adapter:
                register(ctx)
                self.assertEqual(adapter.call_args.kwargs['redact_literals'],['secret'])

class RouteWiringValidationTests(unittest.TestCase):
    def test_route_references_and_effective_scopes_are_cross_checked(self):
        from orpheus.deployment import validate_routes
        deployment={'auth_profiles':{'source':{'scope':'stable','secret_env':'HOOK_SECRET'}},'targets':{'api':{'verified':False}}}
        route={'id':'one','auth_profile':'source','execution_target':'api'}
        validate_routes({'webhooks':[route]},deployment)
        for change in ({'auth_profile':'missing','security_scope':'explicit'}, {'execution_target':'missing'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_routes({'webhooks':[{**route,**change}]},deployment)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            validate_routes({'webhooks':[route,{**route,'id':'two'}]},deployment)
        validate_routes({'webhooks':[route,{**route,'id':'two','security_scope':'separate'}]},deployment)

    def test_plugin_rejects_missing_auth_before_registering_tools(self):
        import yaml
        with tempfile.TemporaryDirectory() as directory:
            config=yaml.safe_load((Path(__file__).parents[1]/'examples/webhook-presets.yaml').read_text())
            config['webhooks'][0]['security_scope']='explicit'
            deployment=yaml.safe_load((Path(__file__).parents[1]/'examples/webhook-deployment.yaml').read_text())
            deployment['auth_profiles']={}
            config_path=Path(directory)/'config.yaml'; config_path.write_text(yaml.safe_dump(config))
            deployment_path=Path(directory)/'deployment.yaml'; deployment_path.write_text(yaml.safe_dump(deployment))
            ctx=Context(directory); ctx.config.update(config_path=str(config_path),deployment_path=str(deployment_path))
            with self.assertRaisesRegex(ValueError,'missing_route_auth_profile'): register(ctx)
            self.assertEqual(ctx.tools,{})
