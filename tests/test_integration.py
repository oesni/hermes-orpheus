"""Whole plugin/registry/resolver/adapter boundary tests with a public host double."""
import asyncio
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml
from orpheus.cli import main
from orpheus.plugin import register
from tests.test_host import Lifecycle
from tests.test_plugin import Context


ROOT = Path(__file__).parents[1]


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ctx=Context(self.directory.name)
        self.addCleanup(lambda:[fn() for fn in self.ctx.cleanups])
        self.config=yaml.safe_load((ROOT/'examples/presets.yaml').read_text())
        self.deployment={'subagent':{'fallback_disabled':True,'verified_settings':[]}}

    def load(self):
        config=Path(self.directory.name)/'config.yaml'
        config.write_text(yaml.safe_dump(self.config))
        deployment=Path(self.directory.name)/'deployment.yaml'
        deployment.write_text(yaml.safe_dump(self.deployment))
        self.ctx.config.update(config_path=str(config),deployment_path=str(deployment))
        register(self.ctx)

    async def tool(self,name,args):
        return json.loads(await self.ctx.tools[name]['handler'](args))

    async def test_model_only_original_schema_through_registered_tool(self):
        preset=self.config['presets'][0]
        preset['compatible_settings']={'only':{'model':'small'}}
        self.deployment['subagent']['verified_settings']=[{'provider':'configured-provider','model':'configured-small-model'}]
        self.load()
        result=await self.tool('orpheus_spawn',{'task':'Analyze evidence','preset_id':'analyst','proposals':{'model':'small'}})
        self.assertEqual(result['state'],'running')
        call=self.ctx.subagent_lifecycle.calls[0]
        self.assertEqual(call['model'],'configured-small-model')
        self.assertIn('Explain conclusions',call['context'])
        self.assertNotIn('reasoning_effort',call)
        status=await self.tool('orpheus_status',{'request_id':result['request_id']})
        self.assertEqual(status['state'],'RUNNING')

    async def test_stock_model_choices_are_per_launch(self):
        self.ctx.subagent_lifecycle=Lifecycle()
        self.deployment['subagent']={'fallback_disabled':True,'verified_settings':[{'provider':'configured-provider','model':model} for model in ('configured-small-model','configured-large-model')]}
        self.load()
        results=await asyncio.gather(*[self.tool('orpheus_spawn',{'task':'Identical task','preset_id':'analyst','proposals':{'model':value}}) for value in ('small','large')])
        self.assertTrue(all(r.get('state')=='running' for r in results),results)
        self.assertEqual([c['model'] for c in self.ctx.subagent_lifecycle.calls],['configured-small-model','configured-large-model'])
        self.assertTrue(all('reasoning_effort' not in c and 'disable_fallback' not in c for c in self.ctx.subagent_lifecycle.calls))
        self.assertEqual(len({c['correlation_id'] for c in self.ctx.subagent_lifecycle.calls}),2)

    async def test_cancel_during_real_resolver_await_prevents_launch(self):
        self.config['policies']['interactive']['field_resolver']={'id':'fields','kind':'jev','model':'jev-pinned','projection_fields':['task.text']}
        self.load()
        entered=asyncio.Event()
        async def blocked_choose(*args,**kwargs):
            entered.set()
            await asyncio.Future()
        with patch('orpheus.jev.JevClient.choose',blocked_choose):
            task=asyncio.create_task(self.tool('orpheus_spawn',{'task':'Wait','preset_id':'analyst'}))
            await asyncio.wait_for(entered.wait(),1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(self.ctx.subagent_lifecycle.calls,[])


class CliTests(unittest.TestCase):
    def run_cli(self,command,config):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.yaml'
            path.write_text(yaml.safe_dump(config))
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                status=main([command,str(path)])
            return status,json.loads(output.getvalue())

    def test_inspect_expands_inventory_to_exact_candidates(self):
        config=yaml.safe_load((ROOT/'examples/presets.yaml').read_text())
        status,report=self.run_cli('inspect',config)
        self.assertEqual(status,0)
        preset=report['presets'][0]
        self.assertEqual(preset['candidate_count'],2)
        self.assertEqual({c['resolved']['model'] for c in preset['expanded_settings']},{'configured-small-model','configured-large-model'})
        self.assertEqual(preset['expanded_settings'][0]['resolved']['provider'],'configured-provider')

    def test_validate_reports_quarantined_definition_nonzero(self):
        config=yaml.safe_load((ROOT/'examples/presets.yaml').read_text())
        config['presets'][0]['fields']['model']['candidates']=[]
        status,report=self.run_cli('validate',config)
        self.assertEqual(status,1)
        self.assertFalse(report['valid'])
        self.assertIn('analyst',report['quarantined'])

class CrossFileCliTests(unittest.TestCase):
    def test_deployment_validation_rejects_missing_refs_without_secrets(self):
        config=yaml.safe_load((ROOT/'examples/webhook-presets.yaml').read_text())
        config['webhooks'][0]['security_scope']='explicit'
        deployment=yaml.safe_load((ROOT/'examples/webhook-deployment.yaml').read_text())
        with tempfile.TemporaryDirectory() as directory:
            config_path=Path(directory)/'config.yaml'; config_path.write_text(yaml.safe_dump(config))
            deployment_path=Path(directory)/'deployment.yaml'
            def run():
                output=io.StringIO()
                with contextlib.redirect_stdout(output):
                    status=main(['validate',str(config_path),'--deployment',str(deployment_path)])
                return status,json.loads(output.getvalue())
            deployment_path.write_text(yaml.safe_dump(deployment))
            self.assertEqual(run()[0],0)  # verified:false and unset environment credentials are allowed offline
            deployment['auth_profiles']={}
            deployment_path.write_text(yaml.safe_dump(deployment))
            status,report=run()
            self.assertEqual(status,1)
            self.assertEqual(report['error'],'missing_route_auth_profile')

    def test_validate_reports_unavailable_routes_even_without_other_errors(self):
        from unittest.mock import patch
        from orpheus.config import Registry
        registry=Registry.from_yaml((ROOT/'examples/presets.yaml').read_text())
        discovery=registry.discover('subagent')
        discovery['unavailable_routes']={'issue-analysis':'policy_unavailable'}
        output=io.StringIO()
        with patch.object(Registry,'from_yaml',return_value=registry), patch.object(registry,'discover',return_value=discovery), contextlib.redirect_stdout(output):
            status=main(['validate',str(ROOT/'examples/presets.yaml')])
        self.assertEqual(status,1)
        report=json.loads(output.getvalue())
        self.assertFalse(report['valid'])
        self.assertEqual(report['unavailable_routes'],{'issue-analysis':'policy_unavailable'})
