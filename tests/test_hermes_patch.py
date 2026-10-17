"""Execute actual patched AST functions with non-provider dependencies stubbed."""
import ast
import contextlib
import dataclasses
import sys
import tempfile
import threading
import types
import typing
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch
from compat.verify_patch import prepare


def definitions(source,names,namespace):
    tree=ast.parse(source)
    keep=[]
    for node in tree.body:
        identifiers=[node.name] if isinstance(node,(ast.FunctionDef,ast.ClassDef)) else [x.id for x in node.targets if isinstance(x,ast.Name)] if isinstance(node,ast.Assign) else [node.target.id] if isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name) else []
        if set(identifiers)&set(names): keep.append(node)
    exec(compile(ast.Module(body=keep,type_ignores=[]),'extracted-upstream','exec'),namespace)


class HermesPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        prepare(self.temp.name); self.root=Path(self.temp.name)
        self.constants=types.ModuleType('hermes_constants')
        definitions((self.root/'hermes_constants.py').read_text(),{'VALID_REASONING_EFFORTS','parse_reasoning_effort'},self.constants.__dict__)
        self.parent=types.SimpleNamespace(reasoning_config={'enabled':True,'effort':'medium'},request_overrides={},session_id='parent',_fallback_chain=[{'model':'backup'}])
        self.created=[]
        self.agent_module=types.ModuleType('run_agent')
        def constructor(**kwargs):
            self.created.append(kwargs)
            return types.SimpleNamespace(session_id='child',**kwargs)
        self.agent_module.AIAgent=constructor
        delegation=types.ModuleType('agent.delegation_context'); delegation.delegated_child_context=contextlib.nullcontext
        hooks=types.ModuleType('hermes_cli.lifecycle'); hooks.invoke_hook=lambda *a,**k:None
        self.delegate=types.ModuleType('tools.delegate_tool')
        self.model_tools=types.ModuleType('model_tools'); self.model_tools._last_resolved_tool_names=['parent_tool']
        self.modules={'hermes_constants':self.constants,'run_agent':self.agent_module,'agent.delegation_context':delegation,'hermes_cli.lifecycle':hooks,'tools.delegate_tool':self.delegate,'model_tools':self.model_tools}
        ns=dict(Any=typing.Any,Optional=typing.Optional,weakref=weakref,
          _get_max_spawn_depth=lambda:1,_get_orchestrator_enabled=lambda:False,
          _load_config=lambda:{},_resolve_child_toolsets=lambda *a:(['terminal'],[]),
          _build_child_system_prompt=lambda *a,**k:'prompt',_resolve_workspace_hint=lambda *a:None,
          _build_child_progress_callback=lambda *a,**k:None,_open_child_session_db=lambda *a:None,
          _apply_child_cache_ttl=lambda *a:None,_apply_child_compression_cap=lambda *a:None,
          _resolve_child_credential_pool=lambda *a,**k:None,_attach_child=lambda *a:None,
          _safe_progress=lambda *a,**k:None,_quiet=lambda *a,**k:contextlib.nullcontext())
        ns['_resolve_child_runtime']=lambda parent,*a,**k:dict(provider='test',model=k['model'],base_url='https://example.invalid',reasoning_config=parent.reasoning_config,fallback_model=parent._fallback_chain)
        definitions((self.root/'tools/delegate_tool.py').read_text(),{'_build_child_agent'},ns)
        self.delegate._build_child_agent=ns['_build_child_agent']
        wrap={'_CHILD_CONSTRUCTION_LOCK':threading.RLock()}
        definitions((self.root/'tools/delegate_tool_results.py').read_text(),{'_build_child_preserving_parent_tools'},wrap)
        self.build=wrap['_build_child_preserving_parent_tools']
        self.patch=patch.dict(sys.modules,self.modules); self.patch.start(); self.addCleanup(self.patch.stop)

    def child(self,**kwargs):
        return self.build(task_index=0,goal='identical',context=None,toolsets=None,model='selected',max_iterations=10,task_count=1,parent_agent=self.parent,**kwargs)

    def test_constructor_first_receives_effort_and_no_fallback(self):
        self.child(reasoning_effort='high',disable_fallback=True)
        self.assertEqual(self.created[0]['reasoning_config'],{'enabled':True,'effort':'high'})
        self.assertIsNone(self.created[0]['fallback_model'])
        self.assertEqual(self.model_tools._last_resolved_tool_names,['parent_tool'])

    def test_identical_siblings_isolated_defaults_preserved(self):
        self.child(reasoning_effort='low',disable_fallback=True)
        self.child(reasoning_effort='high',disable_fallback=True)
        self.child()
        self.assertEqual([x['reasoning_config']['effort'] for x in self.created],['low','high','medium'])
        self.assertEqual(self.created[2]['fallback_model'],[{'model':'backup'}])
        self.assertEqual(self.parent.reasoning_config,{'enabled':True,'effort':'medium'})

    def test_invalid_before_constructor(self):
        for kwargs in ({'reasoning_effort':'typo'},{'reasoning_effort':False},{'disable_fallback':1}):
            with self.assertRaises(ValueError): self.child(**kwargs)
        self.assertEqual(self.created,[])

    def test_public_request_validation_and_marker(self):
        ns=dict(dataclasses=dataclasses,Any=typing.Any,Optional=typing.Optional,Mapping=typing.Mapping,Callable=typing.Callable,_MAX_GOAL_CHARS=16000,_MAX_CONTEXT_CHARS=32000)
        source=(self.root/'agent/subagent_lifecycle.py').read_text()
        definitions(source,{'SubagentLaunchRequest','_valid_launch_effort','_REQUEST_REJECTIONS'},ns)
        request=ns['SubagentLaunchRequest']
        for kwargs in ({'reasoning_effort':'typo'},{'reasoning_effort':False},{'disable_fallback':1}):
            self.assertTrue(any(check(request(goal='x',**kwargs)) for check,_ in ns['_REQUEST_REJECTIONS']))
        for effort in ('low','high','none','ultra',None):
            self.assertFalse(any(check(request(goal='x',reasoning_effort=effort)) for check,_ in ns['_REQUEST_REJECTIONS']))
        cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='SubagentLifecycleService')
        marker=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='capabilities')
        exec(compile(ast.Module(body=[marker],type_ignores=[]),'capabilities','exec'),ns)
        self.assertEqual(ns['capabilities'](None),{'reasoning_effort':'per-launch-v1','disable_fallback':'per-launch-v1'})
        launch=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='launch')
        call=next(n for n in ast.walk(launch) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_build_child_preserving_parent_tools')
        fields={k.arg:ast.unparse(k.value) for k in call.keywords}
        self.assertEqual(fields['reasoning_effort'],'request.reasoning_effort')
        self.assertEqual(fields['disable_fallback'],'request.disable_fallback')

    def test_actual_launch_forwards_request_to_constructor(self):
        source=(self.root/'agent/subagent_lifecycle.py').read_text()
        cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='SubagentLifecycleService')
        launch=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='launch')
        registry=types.SimpleNamespace(lock=threading.RLock(),records={},correlations={})
        class Handle:
            def __init__(self,*args): self.subagent_id=args[1]
        ns=dict(SubagentLaunchRequest=typing.Any,Mapping=typing.Mapping,Any=typing.Any,SubagentHandle=Handle,
                SubagentLifecycleError=ValueError,_coerce_request=lambda r:r,_session_id_of=lambda p:p.session_id,
                _REGISTRY=registry,PUBLIC_CONTRACT_VERSION=1,time=__import__('time'),
                _Record=lambda *a,**kw:types.SimpleNamespace(),SubagentState=types.SimpleNamespace(PENDING='pending'),
                _EXECUTOR=types.SimpleNamespace(submit=lambda *a:None))
        exec(compile(ast.Module(body=[launch],type_ignores=[]),'actual-launch','exec'),ns)
        self.delegate._build_child_preserving_parent_tools=self.build
        self.delegate._credential_overrides=lambda *a:{}
        self.delegate._load_config=lambda:{}
        self.delegate._resolve_delegation_credentials=lambda *a:{'model':'selected'}
        self.delegate.DEFAULT_MAX_ITERATIONS=250
        service=types.SimpleNamespace(_parent_agent_resolver=lambda:self.parent,_validate_request=lambda *a:None,_cleanup_locked=lambda:None,_capability=lambda *a:'cap',_run=lambda *a:None)
        request=types.SimpleNamespace(goal='x',context=None,role='leaf',provider='test',model='selected',allowed_toolsets=None,parent_session_id=None,correlation_id=None,reasoning_effort='high',disable_fallback=True)
        ns['launch'](service,request)
        self.assertEqual(self.created[0]['reasoning_config']['effort'],'high')
        self.assertIsNone(self.created[0]['fallback_model'])

    def test_simultaneous_identical_goals_isolated(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            children=list(pool.map(lambda effort:self.child(reasoning_effort=effort,disable_fallback=True),['low','high']))
        self.assertEqual([c.reasoning_config['effort'] for c in children],['low','high'])
        self.assertEqual(self.parent.reasoning_config['effort'],'medium')
