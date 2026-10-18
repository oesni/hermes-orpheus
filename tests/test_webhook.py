import asyncio
import hashlib
import hmac
import json
import pytest
import functools
def async_test(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs): return asyncio.run(fn(*args, **kwargs))
    return wrapper
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from orpheus.ledger import Ledger
from orpheus.webhook import WebhookService, extract

CONFIG={'webhooks':[{'id':'issue','auth_profile':'source','execution_target':'api','receipt':{'kind':'disabled'},'event_schema':{'event.title':{'source':'body','pointer':'/title','type':'string','max_length':100,'trust':'payload'}},'task_fields':['event.title'],'routing_fields':[]}]}
DEPLOYMENT={'auth_profiles':{'source':{'scope':'stable-source','secret_env':'TEST_HOOK_SECRET'}},'targets':{'api':{'principal':'profile-a'}},'operators':{'TEST_OPERATOR':['stable-source']}}
class Resolver:
    async def resolve(self,*args,**kwargs): return {'model':'large','provider':'provider','effort':'high','instructions':'Analyze'}
class Host:
    def __init__(self): self.calls=[]
    def preflight(self,selection,target): return 'profile-a'
    async def submit(self,payload,key,target): self.calls.append((payload,key,target)); return {'id':'host-run'}
    async def status(self,*args): return {'status':'completed','output':'done'}
    async def cancel(self,*args): return {'status':'stopping'}

@async_test
async def test_authenticated_parallel_replay_and_operator(tmp_path,monkeypatch):
    monkeypatch.setenv('TEST_HOOK_SECRET','secret'); monkeypatch.setenv('TEST_OPERATOR','operator')
    host=Host(); ledger=Ledger(tmp_path/'ledger.db'); service=WebhookService(CONFIG,Resolver(),DEPLOYMENT,ledger,host=host)
    app=web.Application(); service.mount(app)
    async with TestClient(TestServer(app)) as client:
        raw=json.dumps({'title':'task\nnot a new field'}).encode()
        signature='sha256='+hmac.new(b'secret',raw,hashlib.sha256).hexdigest()
        async def send(i):
            return await client.post('/orpheus/webhooks/issue',data=raw,headers={'Content-Type':'application/json','X-Hub-Signature-256':signature,'X-Delivery-ID':str(i)})
        responses=await asyncio.gather(*(send(i) for i in range(10)))
        bodies=[await r.json() for r in responses]
        assert sum(r.status==202 for r in responses)==1
        assert len({r['request_id'] for r in bodies})==1
        for _ in range(50):
            if host.calls: break
            await asyncio.sleep(.01)
        assert len(host.calls)==1
        payload=host.calls[0][0]
        assert payload['model']=='large' and payload['model_options']=={'reasoning_effort':'high'}
        assert not {'session_id','previous_response_id','history'} & payload.keys()
        assert '\\n' in payload['input'] and '\n' not in payload['input']
        rid=bodies[0]['request_id']
        assert (await client.get('/orpheus/requests/'+rid)).status==403
        response=await client.get('/orpheus/requests/'+rid,headers={'Authorization':'Bearer operator'})
        assert response.status==200
        assert 'registry_snapshot' not in await response.json()
        bad=await client.post('/orpheus/webhooks/issue',data=raw,headers={'Content-Type':'application/json'})
        assert bad.status==401
        unicode_signature=await client.post('/orpheus/webhooks/issue',data=raw,headers={'Content-Type':'application/json','X-Hub-Signature-256':'sha256=é'})
        assert unicode_signature.status==401

@async_test
async def test_ambiguous_acceptance_not_resubmitted(tmp_path):
    class Broken(Host):
        async def submit(self,*args): self.calls.append(args); raise TimeoutError()
    host=Broken(); ledger=Ledger(tmp_path/'db'); service=WebhookService(CONFIG,Resolver(),DEPLOYMENT,ledger,host=host)
    row,_=ledger.reserve('scope','body',{'route_id':'issue','registry_snapshot':CONFIG,'task':'task','context':{},'target':'api','principal':'profile-a'})
    await service.process(row)
    unknown=ledger.get(row['id']); assert unknown['state']=='unknown'
    await service.observe(unknown); await service.process(unknown)
    assert len(host.calls)==1
    ledger.close()


def test_extraction_no_coercion_and_trust_spoof():
    with pytest.raises(ValueError): extract(CONFIG['webhooks'][0],{'title':42})
    route={'event_schema':{'identity':{'source':'body','pointer':'/id','type':'string','trust':'verified_metadata'}}}
    with pytest.raises(ValueError): extract(route,{'id':'admin'})

@async_test
async def test_real_public_run_http_boundary(tmp_path,monkeypatch):
    from orpheus.webhook import RunClient
    monkeypatch.setenv('TEST_HOOK_SECRET','secret'); monkeypatch.setenv('TEST_HOST_TOKEN','host-secret')
    calls=[]
    async def runs(request):
        assert request.headers['Authorization']=='Bearer host-secret'
        assert request.headers['Idempotency-Key'].startswith('orpheus-')
        assert 'X-Hermes-Session-Key' not in request.headers
        calls.append(await request.json())
        return web.json_response({'run_id':'native-1'})
    upstream=web.Application(); upstream.router.add_post('/v1/runs',runs)
    async with TestServer(upstream) as server:
        deployment={**DEPLOYMENT,'targets':{'api':{'url':str(server.make_url('')).rstrip('/'),'token_env':'TEST_HOST_TOKEN','principal':'profile-a','verified':True,'fallback_disabled':True,'allow_loopback_http':True,'models':{'large':{'provider':'provider','efforts':['high']}}}}}
        ledger=Ledger(tmp_path/'db'); service=WebhookService(CONFIG,Resolver(),deployment,ledger)
        app=web.Application(); service.mount(app)
        async with TestClient(TestServer(app)) as client:
            raw=b'{"title":"task"}'; signature='sha256='+hmac.new(b'secret',raw,hashlib.sha256).hexdigest()
            response=await client.post('/orpheus/webhooks/issue',data=raw,headers={'Content-Type':'application/json','X-Hub-Signature-256':signature})
            assert response.status==202
            for _ in range(100):
                if calls: break
                await asyncio.sleep(.01)
            assert calls==[{'input':'event.title: "task"','model':'large','provider':'provider','model_options':{'reasoning_effort':'high'},'instructions':'Analyze'}]

@async_test
async def test_cancel_during_selection_prevents_submit(tmp_path):
    entered=asyncio.Event(); release=asyncio.Event()
    class WaitingResolver:
        async def resolve(self,*args,**kwargs):
            entered.set(); await release.wait()
            return {'model':'large','provider':'provider','effort':'high'}
    ledger=Ledger(tmp_path/'db'); host=Host(); service=WebhookService(CONFIG,WaitingResolver(),DEPLOYMENT,ledger,host=host)
    row,_=ledger.reserve('scope','body',{'route_id':'issue','registry_snapshot':CONFIG,'task':'task','context':{},'target':'api','principal':'profile-a'})
    work=asyncio.create_task(service.process(row)); await entered.wait()
    assert ledger.cancel(row['id'])['state']=='cancelled'
    release.set(); await work
    assert host.calls==[]
    ledger.close()

@async_test
async def test_expired_starting_never_dispatches(tmp_path):
    ledger=Ledger(tmp_path/'db'); host=Host(); service=WebhookService(CONFIG,Resolver(),DEPLOYMENT,ledger,host=host)
    row,_=ledger.reserve('scope','body',{'route_id':'issue','registry_snapshot':CONFIG,'task':'task','context':{},'target':'api','principal':'profile-a'})
    ledger.change(row['id'],1,('resolving',),'starting',payload={'input':'task'})
    ledger.db.execute('UPDATE runs SET lease=0')
    recovered=ledger.claim(row['id']); recovered['_recovered']=True; await service.observe(recovered)
    assert ledger.get(row['id'])['state']=='unknown'
    assert host.calls==[]
    ledger.close()

@async_test
async def test_real_registry_rules_and_filter_before_selection(tmp_path,monkeypatch):
    import copy
    from orpheus.config import Registry
    from orpheus.resolver import Resolver as ActualResolver
    monkeypatch.setenv('TEST_HOOK_SECRET','secret'); monkeypatch.setenv('TEST_HOST_TOKEN','host-secret')
    route=copy.deepcopy(CONFIG['webhooks'][0]); route['policy']='incoming'
    route['filters']={'not':{'field':'event.title','op':'eq','value':'ignore'}}
    route['routing_fields']=['event.title']
    config={'schema_version':1,'inventory':{'models':{'small':{'provider':'p','model':'m','efforts':['low','high']}}},'presets':[{'id':'analyst','fields':{'model':{'mode':'fixed','value':'small'},'effort':{'mode':'enum','candidates':['low','high']}},'compatible_settings':{'quick':{'effort':'low'},'deep':{'effort':'high'}}}], 'policies':{'incoming':{'entrypoint':'webhook','preset_selector':{'id':'p','kind':'fixed','preset':'analyst'},'field_resolver':{'id':'f','kind':'rules','rules':[{'id':'deep','priority':1,'when':{'field':'event.title','op':'eq','value':'complex'},'settings':'deep'}],'no_match':{'kind':'fixed','settings':'quick'}}}},'webhooks':[route]}
    registry=Registry.from_dict(config); assert not registry.unavailable_policies
    calls=[]
    async def runs(request):
        assert request.headers['Authorization']=='Bearer host-secret'
        calls.append(await request.json()); return web.json_response({'id':'run-'+str(len(calls))})
    upstream=web.Application(); upstream.router.add_post('/v1/runs',runs)
    async with TestServer(upstream) as server:
        deployment={**DEPLOYMENT,'targets':{'api':{'url':str(server.make_url('')).rstrip('/'),'token_env':'TEST_HOST_TOKEN','principal':'profile-a','verified':True,'fallback_disabled':True,'allow_loopback_http':True,'models':{'m':{'provider':'p','efforts':['low','high']}}}}}
        ledger=Ledger(tmp_path/'db'); service=WebhookService(registry,ActualResolver(registry),deployment,ledger)
        app=web.Application(); service.mount(app)
        async with TestClient(TestServer(app)) as client:
            async def send(title):
                raw=json.dumps({'title':title}).encode(); signature='sha256='+hmac.new(b'secret',raw,hashlib.sha256).hexdigest()
                return await client.post('/orpheus/webhooks/issue',data=raw,headers={'Content-Type':'application/json','X-Hub-Signature-256':signature})
            rejected=await send('ignore'); assert rejected.status==200 and (await rejected.json())['reason']=='filtered'
            assert calls==[] and ledger.active()==[]
            responses=await asyncio.gather(send('complex'),send('routine'))
            assert all(response.status==202 for response in responses)
            for _ in range(100):
                if len(calls)==2: break
                await asyncio.sleep(.01)
            assert len(calls)==2
            assert {p['input']:p['model_options']['reasoning_effort'] for p in calls}=={'event.title: "complex"':'high','event.title: "routine"':'low'}
            assert all(p['provider']=='p' and p['model']=='m' for p in calls)


def test_extraction_rejects_enum_bool_integer_alias_and_nonfinite():
    for spec,value in [({'type':'enum','values':[True]},1),({'type':'enum','values':[1]},True),({'type':'number'},float('inf'))]:
        route={'event_schema':{'event.value':dict(spec,source='body',pointer='/value',trust='payload')}}
        with pytest.raises(ValueError): extract(route,{'value':value})
    assert json.loads('{"value":1e999}')['value']==float('inf')


def test_route_path_must_match_registered_endpoint(tmp_path):
    import copy
    config=copy.deepcopy(CONFIG); config['webhooks'][0]['path']='/ignored/path'
    ledger=Ledger(tmp_path/'db')
    with pytest.raises(ValueError,match='unsupported_route_path'):
        WebhookService(config,Resolver(),DEPLOYMENT,ledger,host=Host())
    ledger.close()

@async_test
async def test_route_security_scopes_isolate_same_signed_body(tmp_path,monkeypatch):
    import copy
    monkeypatch.setenv('TEST_HOOK_SECRET','secret')
    config=copy.deepcopy(CONFIG); second=copy.deepcopy(config['webhooks'][0]); second['id']='other'; config['webhooks'].append(second)
    ledger=Ledger(tmp_path/'db'); host=Host()
    with pytest.raises(ValueError,match='duplicate_route_security_scope'):
        WebhookService(config,Resolver(),DEPLOYMENT,ledger,host=host)
    second['security_scope']='distinct-stable-route'
    service=WebhookService(config,Resolver(),DEPLOYMENT,ledger,host=host)
    app=web.Application(); service.mount(app)
    async with TestClient(TestServer(app)) as client:
        raw=b'{"title":"task"}'; signature='sha256='+hmac.new(b'secret',raw,hashlib.sha256).hexdigest()
        headers={'Content-Type':'application/json','X-Hub-Signature-256':signature}
        first=await client.post('/orpheus/webhooks/issue',data=raw,headers=headers)
        other=await client.post('/orpheus/webhooks/other',data=raw,headers=headers)
        assert first.status==other.status==202
        assert (await first.json())['request_id']!=(await other.json())['request_id']
        for _ in range(100):
            if len(host.calls)==2: break
            await asyncio.sleep(.01)
        assert len(host.calls)==2

@async_test
async def test_terminal_cancel_is_noop_and_partial_result_expires(tmp_path):
    class ObservedHost(Host):
        def __init__(self): super().__init__(); self.stops=0; self.outputs=[{'status':'running','output':'partial'},{'status':'completed'}]
        async def status(self,*args): return self.outputs.pop(0)
        async def cancel(self,*args): self.stops+=1
    ledger=Ledger(tmp_path/'db'); host=ObservedHost(); service=WebhookService(CONFIG,Resolver(),DEPLOYMENT,ledger,host=host)
    row,_=ledger.reserve('scope','body',{'route_id':'issue','registry_snapshot':CONFIG,'task':'task','context':{},'target':'api','principal':'profile-a'})
    await service.process(row)
    await service.observe(ledger.get(row['id']))
    assert ledger.get(row['id'])['result']=='partial'
    await service.observe(ledger.get(row['id']))
    terminal=ledger.get(row['id'])
    assert terminal['state']=='completed' and terminal['result_availability']=='available'
    assert terminal['result_is_partial'] and terminal['result_expires']>terminal['updated']
    after=ledger.cancel(row['id']); await service.observe(after)
    assert after==terminal and host.stops==0
    ledger.close()


@async_test
async def test_reconcile_while_submit_and_late_acceptance_survives_new_owner(tmp_path):
    entered=asyncio.Event(); release=asyncio.Event()
    class Delayed(Host):
        async def submit(self,*args): entered.set(); await release.wait(); return {'id':'late-host'}
    ledger=Ledger(tmp_path/'db'); service=WebhookService(CONFIG,Resolver(),DEPLOYMENT,ledger,host=Delayed())
    row,_=ledger.reserve('scope','body',{'route_id':'issue','registry_snapshot':CONFIG,'task':'task','context':{},'target':'api','principal':'profile-a'})
    task=asyncio.create_task(service.process(row)); await entered.wait()
    # An operator without an expired lease cannot turn an active submit unknown.
    await service.observe(ledger.get(row['id']))
    assert ledger.get(row['id'])['state']=='starting'
    # A recovered owner may mark ambiguity, but the unique dispatch receipt survives.
    ledger.db.execute('UPDATE runs SET lease=0 WHERE id=?',(row['id'],))
    recovered=ledger.claim(row['id']); recovered['_recovered']=True
    await service.observe(recovered)
    assert ledger.get(row['id'])['state']=='unknown'
    ledger.cancel(row['id'])
    release.set(); await task
    result=ledger.get(row['id'])
    assert result['state']=='running' and result['host_id']=='late-host' and result['cancel_requested']
    assert result['generation']==2
    assert not ledger.publish_acceptance(row['id'],'wrong',result['idempotency_key'],result['payload_digest'],'other-host')
    ledger.close()

@async_test
async def test_observation_uses_origin_principal_not_policy_config(tmp_path):
    import copy
    deployment=copy.deepcopy(DEPLOYMENT); deployment['targets']['api']['url']='https://same.example'
    host=Host(); ledger=Ledger(tmp_path/'db'); service=WebhookService(CONFIG,Resolver(),deployment,ledger,host=host)
    row,_=ledger.reserve('scope','body',{'target':'api','target_snapshot':copy.deepcopy(deployment['targets']['api']),'principal':'profile-a'})
    ledger.change(row['id'],1,('resolving',),'running',host_id='host')
    deployment['targets']['api'].update(token_env='ROTATED',verified=False)
    await service.observe(ledger.get(row['id']))
    assert ledger.get(row['id'])['state']=='completed'
    second,_=ledger.reserve('scope','other',{'target':'api','target_snapshot':{'url':'https://different.example','principal':'profile-a'},'principal':'profile-a'})
    ledger.change(second['id'],1,('resolving',),'running',host_id='host2')
    await service.observe(ledger.get(second['id']))
    assert ledger.get(second['id'])['state']=='unknown'
    assert ledger.get(second['id'])['error']['code']=='target_identity_changed'
    ledger.close()


@async_test
async def test_reconciler_survives_ledger_errors(tmp_path,monkeypatch):
    ledger=Ledger(tmp_path/'db'); service=WebhookService(CONFIG,Resolver(),DEPLOYMENT,ledger,host=Host())
    service.owners={'already-terminal':1}
    counts={'active':0,'expire':0,'sleep':0}
    def active():
        counts['active']+=1
        if counts['active']==1: raise RuntimeError('temporary lock')
        return []
    def expire():
        counts['expire']+=1
        if counts['expire']==1: raise RuntimeError('temporary error')
    async def sleep(_):
        counts['sleep']+=1
        if counts['sleep']==3: raise asyncio.CancelledError()
    monkeypatch.setattr(ledger,'active',active); monkeypatch.setattr(ledger,'expire_results',expire)
    monkeypatch.setattr(asyncio,'sleep',sleep)
    with pytest.raises(asyncio.CancelledError): await service.reconcile()
    assert counts=={'active':3,'expire':3,'sleep':3}
    assert service.owners=={}
    ledger.close()


@async_test
async def test_restart_missing_host_run_and_stop_become_unknown(tmp_path,monkeypatch):
    import copy
    monkeypatch.setenv('TEST_HOST_TOKEN','token')
    calls=[]
    async def missing(request):
        calls.append(request.path); return web.json_response({'error':'expired'},status=404)
    host_app=web.Application(); host_app.router.add_get('/v1/runs/{id}',missing); host_app.router.add_post('/v1/runs/{id}/stop',missing)
    async with TestServer(host_app) as server:
        deployment=copy.deepcopy(DEPLOYMENT); deployment['targets']['api'].update(url=str(server.make_url('')).rstrip('/'),token_env='TEST_HOST_TOKEN')
        path=tmp_path/'db'; ledger=Ledger(path); ids=[]
        for cancel in (False,True):
            row,_=ledger.reserve('scope',str(cancel),{'target':'api','principal':'profile-a','target_snapshot':copy.deepcopy(deployment['targets']['api'])})
            ledger.change(row['id'],1,('resolving',),'running',host_id='expired',cancel_requested=cancel)
            ids.append(row['id'])
        ledger.db.execute('UPDATE runs SET lease=0'); ledger.close()
        ledger=Ledger(path); service=WebhookService(CONFIG,Resolver(),deployment,ledger)
        for rid in ids:
            recovered=ledger.claim(rid); await service.observe(recovered)
            saved=ledger.get(rid)
            assert saved['state']=='unknown' and saved['error']['code']=='host_run_unavailable'
            assert saved['result_availability']=='unavailable' and saved['retention_at'] is not None
        assert calls==['/v1/runs/expired','/v1/runs/expired/stop']
        ledger.close()

@async_test
async def test_empty_extracted_task_rejected_before_reservation(tmp_path,monkeypatch):
    import copy
    monkeypatch.setenv('TEST_HOOK_SECRET','secret')
    config=copy.deepcopy(CONFIG); config['webhooks'][0]['event_schema']['event.title']['required']=False
    ledger=Ledger(tmp_path/'db'); host=Host(); service=WebhookService(config,Resolver(),DEPLOYMENT,ledger,host=host)
    app=web.Application(); service.mount(app)
    async with TestClient(TestServer(app)) as client:
        raw=b'{}'; signature='sha256='+hmac.new(b'secret',raw,hashlib.sha256).hexdigest()
        response=await client.post('/orpheus/webhooks/issue',data=raw,headers={'Content-Type':'application/json','X-Hub-Signature-256':signature})
        assert response.status==400 and (await response.json())['reason']=='empty_task'
        assert ledger.active()==[] and host.calls==[]


def test_missing_auth_with_explicit_scope_rejected_at_load(tmp_path):
    import copy
    config=copy.deepcopy(CONFIG); config['webhooks'][0].update(auth_profile='missing',security_scope='explicit')
    ledger=Ledger(tmp_path/'db')
    with pytest.raises(ValueError): WebhookService(config,Resolver(),DEPLOYMENT,ledger,host=Host())
    ledger.close()


@async_test
async def test_permanent_observation_failure_waits_for_explicit_reconcile(tmp_path,monkeypatch):
    from orpheus.webhook import HostRunUnavailable
    monkeypatch.setenv('TEST_OPERATOR','operator')
    class Gone(Host):
        def __init__(self): super().__init__(); self.reads=0
        async def status(self,*args): self.reads+=1; raise HostRunUnavailable()
    ledger=Ledger(tmp_path/'db'); host=Gone(); service=WebhookService(CONFIG,Resolver(),DEPLOYMENT,ledger,host=host)
    row,_=ledger.reserve('stable-source','body',{'target':'api','principal':'profile-a'})
    ledger.change(row['id'],1,('resolving',),'running',host_id='expired')
    await service.observe(ledger.get(row['id']))
    assert host.reads==1 and ledger.active()==[]
    # A second periodic pass has no candidate and performs no host call.
    for pending in ledger.active(): await service.observe(pending)
    assert host.reads==1
    app=web.Application(); service.mount(app)
    async with TestClient(TestServer(app)) as client:
        response=await client.post('/orpheus/requests/'+row['id']+'/reconcile',json={},headers={'Authorization':'Bearer operator'})
        assert response.status==200 and host.reads==2
        assert (await response.json())['state']=='unknown'

@async_test
async def test_transient_observation_failure_remains_pollable(tmp_path):
    class Transient(Host):
        def __init__(self): super().__init__(); self.reads=0
        async def status(self,*args): self.reads+=1; raise RuntimeError('host 503')
    ledger=Ledger(tmp_path/'db'); host=Transient(); service=WebhookService(CONFIG,Resolver(),DEPLOYMENT,ledger,host=host)
    row,_=ledger.reserve('stable-source','body',{'target':'api','principal':'profile-a'})
    ledger.change(row['id'],1,('resolving',),'running',host_id='run')
    await service.observe(ledger.get(row['id']))
    for pending in ledger.active(): await service.observe(pending)
    assert host.reads==2 and ledger.get(row['id'])['state']=='running'
    ledger.close()


@async_test
async def test_ended_dispatch_publication_failure_becomes_abandonable(tmp_path,monkeypatch):
    import sqlite3
    ledger=Ledger(tmp_path/'db'); host=Host(); service=WebhookService(CONFIG,Resolver(),DEPLOYMENT,ledger,host=host)
    row,_=ledger.reserve('scope','body',{'route_id':'issue','registry_snapshot':CONFIG,'task':'task','context':{},'target':'api','principal':'profile-a'})
    def failed_publication(*args): raise sqlite3.OperationalError('transient lock')
    monkeypatch.setattr(ledger,'publish_acceptance',failed_publication)
    service.schedule(row)
    await asyncio.gather(*list(service.tasks))
    await asyncio.sleep(0)
    assert ledger.get(row['id'])['state']=='starting' and row['id'] not in service.jobs
    passes=0
    async def sleep(_):
        nonlocal passes
        passes+=1
        if passes==2: raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio,'sleep',sleep)
    with pytest.raises(asyncio.CancelledError): await service.reconcile()
    saved=ledger.get(row['id'])
    assert saved['state']=='unknown' and saved['error']['code']=='dispatch_completion_unconfirmed'
    assert ledger.active()==[] and service.owners=={} and service.jobs=={}
    assert len(host.calls)==1 and ledger.abandon(row['id'])
    ledger.close()

@async_test
async def test_reconciler_does_not_steal_live_starting_owner(tmp_path,monkeypatch):
    ledger=Ledger(tmp_path/'db'); service=WebhookService(CONFIG,Resolver(),DEPLOYMENT,ledger,host=Host())
    foreign,_=ledger.reserve('s','foreign',{})
    local,_=ledger.reserve('s','local',{})
    for row in (foreign,local): ledger.change(row['id'],1,('resolving',),'starting')
    service.owners[local['id']]=1
    blocker=asyncio.create_task(asyncio.Event().wait()); service.jobs[local['id']]=blocker
    async def sleep(_): raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio,'sleep',sleep)
    with pytest.raises(asyncio.CancelledError): await service.reconcile()
    assert ledger.get(foreign['id'])['state']=='starting' and ledger.get(foreign['id'])['generation']==1
    assert ledger.get(local['id'])['state']=='starting' and ledger.get(local['id'])['generation']==1
    blocker.cancel(); await asyncio.gather(blocker,return_exceptions=True)
    ledger.close()

@async_test
async def test_restart_rebuild_preserves_legacy_injected_client(tmp_path):
    import copy
    class Snapshot(dict):
        @classmethod
        def from_dict(cls, value):
            return cls(value)
    client = object()
    rebuilt = []
    class LegacyResolver:
        def __init__(self, registry, jev_client=None):
            self.jev_client = jev_client
            rebuilt.append((registry, jev_client))
        async def resolve(self, *args, **kwargs):
            assert self.jev_client is client
            return {'model': 'large', 'provider': 'provider'}
    current = Snapshot(copy.deepcopy(CONFIG))
    saved = copy.deepcopy(CONFIG)
    saved['saved_revision'] = 'old'
    ledger = Ledger(tmp_path / 'db')
    host = Host()
    service = WebhookService(current, LegacyResolver(current, client), DEPLOYMENT, ledger, host=host)
    row, _ = ledger.reserve('scope', 'body', {'route_id': 'issue', 'registry_snapshot': saved,
        'task': 'task', 'context': {}, 'target': 'api', 'principal': 'profile-a'})
    await service.process(row)
    assert rebuilt[-1] == (saved, client)
    assert len(host.calls) == 1
