"""Offline extracted-source/stub probe. No Hermes gateway or model API is started."""
import ast
import asyncio
import dataclasses
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import sys
import types
from contextlib import nullcontext

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else '/private/tmp/orpheus-webhook-verify')
used = []
def extract(path, names):
    data = (ROOT / path).read_bytes()
    used.append((path, hashlib.sha256(data).hexdigest()))
    tree = ast.parse(data)
    found = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names:
            found.append(n)
    assert len(found) == len(names)
    return compile(ast.fix_missing_locations(ast.Module(body=found, type_ignores=[])), path, 'exec')

def module(name):
    obj = types.ModuleType(name);sys.modules[name] = obj;return obj

module('gateway'); module('hermes_cli'); module('agent')
ingress = module('gateway.session_ingress')
ingress.executing_admission = types.SimpleNamespace(get=lambda: False)
life = module('hermes_cli.lifecycle')
async def hook(*args, **kwargs):
    return [{'action': 'allow', 'model': 'chosen-model', 'provider': 'chosen-provider'}]
life.ainvoke_hook = hook
ns = {'MessageEvent': object, 'SessionSource': object, 'Optional': __import__('typing').Optional,
      'logger': logging.getLogger('probe'), 'dataclasses': dataclasses}
exec(extract('gateway/run_inbound_hooks.py', {'_hm_pre_gateway_dispatch_hook'}), ns)
event = types.SimpleNamespace(text='task', source=types.SimpleNamespace(platform=None, chat_id='x'))
result = asyncio.run(ns['_hm_pre_gateway_dispatch_hook'](types.SimpleNamespace(), event, event.source))
assert result is event and not hasattr(result, 'model')
print('PASS: native pre_gateway_dispatch allow result ignores model/provider fields')

plugins = module('hermes_cli.plugins')
plugins.has_middleware = lambda kind: True
plugins.invoke_middleware = lambda *args, **kw: iter([{'request': {**kw['request'], 'model': 'chosen-model'}}])
plugins._delivery_manager = lambda: types.SimpleNamespace(_middleware={})
p = ROOT/'hermes_cli/middleware.py';used.append(('hermes_cli/middleware.py',hashlib.sha256(p.read_bytes()).hexdigest()))
spec = importlib.util.spec_from_file_location('hermes_cli.middleware', p)
mw = importlib.util.module_from_spec(spec);sys.modules[spec.name] = mw;spec.loader.exec_module(mw)
r = mw.apply_llm_request_middleware({'model': 'original-model', 'messages': []}, session_id='s')
assert r.payload['model'] == 'chosen-model'
assert r.original_payload['model'] == 'original-model'
print('PASS: actual request middleware rewrites provider request model without mutating original')

relay = module('agent.relay_llm')
relay.execute = lambda request, callback, **kwargs: callback(request)
seen = []
a = types.SimpleNamespace(api_mode='chat_completions', provider='original-provider',
    model='original-model', session_id='s', platform='webhook',base_url='https://original.invalid',
    _interruptible_api_call=lambda request: seen.append(dict(request)) or 'stub-response',
    _has_pending_redirect=lambda:False)
ns = {'Any': object,'dataclass': dataclasses.dataclass,'nullcontext': nullcontext,
      '_should_stream':lambda a:False}
exec(extract('agent/turn_api_call.py', {'ApiCallVerdict','perform_api_call'}), ns)
v=ns['perform_api_call'](a,api_kwargs=r.payload,_original_api_kwargs=r.original_payload,
    _llm_middleware_trace=r.trace,_moa_prepared_request=None,_retry=None,thinking_spinner=None,
    retry_count=0,api_call_count=1,api_request_id='r',effective_task_id='t',turn_id='u',interrupted=False)
assert seen[0]['model']=='chosen-model' and v.response=='stub-response'
assert (a.model,a.provider,a.base_url)==('original-model','original-provider','https://original.invalid')
print('PASS: actual extracted dispatch sends rewritten model through ORIGINAL agent callback; model/provider/base_url identity unchanged')
Path(__file__).with_name('source-sha256.json').write_text(json.dumps(dict(used),indent=2)+'\n')
print('LIMIT: isolated source execution with stub registry/transport; no live Hermes integration, credentials or paid API calls')

# Public native API request path: decode actual request and execute actual selection function.
ROOT = Path('/tmp/orpheus-extension-check')
api = module('gateway.platforms.api_server')
api._REASONING_EFFORTS = frozenset({'none','minimal','low','medium','high','xhigh','max','ultra'})
ns = {'Any':object,'Optional':__import__('typing').Optional,'logger':logging.getLogger('probe')}
exec(extract('gateway/platforms/api_server.py', {'_clean_request_string','_request_agent_overrides','_select_agent_runtime'}),ns)
exec(extract('gateway/platforms/api_server_request_options.py', {'_request_reasoning_config'}),ns)
opts=ns['_request_agent_overrides']({'model':'selected-model','provider':'selected-provider','model_options':{'reasoning_effort':'high'}},virtual_model='hermes-agent')
assert opts=={'requested_model':'selected-model','requested_provider':'selected-provider','model_options':{'reasoning_effort':'high'}}
assert ns['_request_reasoning_config'](opts['model_options'])=={'enabled':True,'effort':'high'}
switch=module('hermes_cli.model_switch');switch.resolve_effective_model=lambda *args:None
calls=[]
def resolve(runtime,provider,**kwargs):
    calls.append((provider,kwargs));runtime.update(provider=provider,base_url='https://selected.invalid');return True
runner=types.SimpleNamespace(_session_model_override_for=lambda key:None,_apply_provider_runtime=resolve,_recover_or_record_model=lambda model,*args:model)
runtime={'provider':'original-provider','base_url':'https://original.invalid'}
selected=ns['_select_agent_runtime'](runner,runtime,'original-model',requested_model=opts['requested_model'],requested_provider=opts['requested_provider'],route=None,session_model=None,confirmed_runtime_lock=False,gateway_session_key=None,session_id='fresh')
assert selected[0]=='selected-model' and runtime['provider']=='selected-provider'
assert calls==[('selected-provider',{'target_model':'selected-model','required':True})]
print('PASS: actual API request decoder and runtime selector resolve requested model/provider for a fresh unaliased session; provider resolver is stubbed')
print('PASS: actual model_options decoder maps high effort to enabled reasoning_config')
# Census actual endpoint launch and constructor keyword wiring without executing network/session code.
for p in ['gateway/platforms/api_server.py','gateway/platforms/api_server_runs.py']:
    data=(ROOT/p).read_bytes();used.append((p,hashlib.sha256(data).hexdigest()))
    tree=ast.parse(data)
    if p.endswith('api_server_runs.py'):
        fn=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='_handle_runs')
        launch=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_RunLaunch')
        code=ast.unparse(next(k.value for k in launch.keywords if k.arg=='agent_kwargs'))
        assert all(s in code for s in ['requested_model','requested_provider','model_options','agent_overrides'])
    else:
        fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_create_agent')
        code=ast.unparse(fn)
        assert "'reasoning_config': request_reasoning_config" in code and 'agent = AIAgent(**agent_kwargs)' in code
print('PASS (AST only): /v1/runs forwards all three override fields; constructor wiring includes resolved model/runtime/reasoning_config')
Path(__file__).with_name('source-sha256.json').write_text(json.dumps(dict(used),indent=2)+'\n')
