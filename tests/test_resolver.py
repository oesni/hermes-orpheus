import unittest
from orpheus.config import Registry
from orpheus.resolver import Resolver, SelectionError
try:
    from tests.test_config import sample
except ImportError:
    from test_config import sample


class ResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_parent_tuple(self):
        result=await Resolver(Registry.from_dict(sample())).resolve('subagent','analyze',preset_id='analyst',proposals={'effort':'high'})
        self.assertEqual(result['resolved'],{'model':'m','provider':'p','effort':'high'})
    async def test_ambiguous_effort(self):
        with self.assertRaises(SelectionError): await Resolver(Registry.from_dict(sample())).resolve('subagent','analyze',preset_id='analyst')
    async def test_fixed_override(self):
        with self.assertRaises(SelectionError): await Resolver(Registry.from_dict(sample())).resolve('subagent','analyze',preset_id='analyst',proposals={'model':'other','effort':'high'})
    async def test_unknown_context(self):
        with self.assertRaises(SelectionError): await Resolver(Registry.from_dict(sample())).resolve('subagent','analyze',context={'verified_metadata':True},preset_id='analyst',proposals={'effort':'high'})
    async def test_rules_and_no_bypass(self):
        config=sample(); config['policies']['interactive']['field_resolver']={'id':'f','kind':'rules','rules':[{'id':'deep','priority':1,'when':{'field':'context.kind','op':'eq','value':'complex'},'settings':'deep'}],'no_match':{'kind':'fixed','settings':'quick'}}
        resolver=Resolver(Registry.from_dict(config))
        result=await resolver.resolve('subagent','analyze',context={'kind':'complex'},preset_id='analyst')
        self.assertEqual(result['effort'],'high')
        with self.assertRaises(SelectionError): await resolver.resolve('subagent','analyze',preset_id='analyst',proposals={})
    async def test_jev_projection(self):
        config=sample(); config['policies']['interactive']['field_resolver']={'id':'f','kind':'jev','model':'jev-pinned','projection_fields':['context.kind']}
        class Fake:
            async def choose(self,**kwargs):
                self.args=kwargs; return {'choice':'deep'}
        fake=Fake(); resolver=Resolver(Registry.from_dict(config),fake)
        await resolver.resolve('subagent','private task',context={'kind':'complex'},preset_id='analyst')
        self.assertEqual(fake.args['state'],{'context.kind':'complex'}); self.assertEqual(set(fake.args['choices']),{'quick','deep'})
    async def test_fallback_only_configured(self):
        config=sample(); p=config['policies']['interactive']; p['field_resolver']={'id':'f','kind':'jev','model':'jev-pinned','projection_fields':[], 'on_error':[{'id':'timeout-edge','errors':['timeout'],'target':'safe'}]}; p['resolver_nodes']={'safe':{'id':'safe','kind':'fixed','settings':'quick'}}
        class Fake:
            async def choose(self,**kwargs): raise SelectionError('timeout','timeout')
        result=await Resolver(Registry.from_dict(config),Fake()).resolve('subagent','task',preset_id='analyst')
        self.assertEqual(result['effort'],'low'); self.assertTrue(any(x.get('edge')=='timeout-edge' for x in result['attempts']))

    async def test_jev_field_guidance_full_resolved_settings(self):
        import json
        config=sample(); preset=config['presets'][0]; preset['purpose']='Analyze'; preset['guidance']='Complex tasks need high effort'; preset['fields']['instructions']={'mode':'fixed','value':'Explain evidence'}
        config['policies']['interactive']['field_resolver']={'id':'f','kind':'jev','model':'jev-pinned','projection_fields':['context.kind']}
        class Fake:
            async def choose(self,**kwargs):
                self.args=kwargs; return {'choice':'deep'}
        fake=Fake()
        await Resolver(Registry.from_dict(config),fake).resolve('subagent','excluded task',context={'kind':'complex'},preset_id='analyst')
        description=json.loads(fake.args['choices']['deep'])
        self.assertEqual(description['guidance'],'Complex tasks need high effort')
        self.assertEqual(description['settings'],{'model':'m','provider':'p','effort':'high','instructions':'Explain evidence'})
        self.assertEqual(fake.args['state'],{'context.kind':'complex'})

    async def test_runtime_rule_values_restricted_to_routing_fields(self):
        from tests.test_config import ConfigTests
        config=ConfigTests().webhook_config()
        config['policies']['incoming']['field_resolver']={'id':'f','kind':'rules','rules':[{'id':'r','priority':1,'when':{'field':'event.title','op':'exists'},'settings':'deep'}]}
        registry=Registry.from_dict(config)
        # Defense in depth: even a previously compiled predicate cannot see a
        # field removed from the route's routing projection before admission.
        registry.webhooks['issue']['routing_fields']=[]
        with self.assertRaises(SelectionError) as error:
            await Resolver(registry).resolve('webhook','task',context={'event.title':'complex'},route_id='issue')
        self.assertEqual(error.exception.code,'no_match')
