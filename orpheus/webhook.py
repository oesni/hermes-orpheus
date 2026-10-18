"""Authenticated new-session ingress through Hermes' public run API."""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
import logging
from pathlib import Path
from urllib.parse import urlparse, quote
import aiohttp
from aiohttp import web
from .ledger import Ledger, Conflict
from .config import Registry, typed
from .resolver import matches
from .deployment import validate_deployment, validate_routes, secure_state_directory

logger=logging.getLogger(__name__)


class HostRunUnavailable(Exception):
    pass


class LaunchRejected(Exception):
    pass


def pointer(body, path):
    value=body
    if path == '': return value
    if not isinstance(path,str) or not path.startswith('/'): raise ValueError('invalid_pointer')
    for item in path[1:].split('/'):
        key=item.replace('~1','/').replace('~0','~')
        if isinstance(value,dict): value=value[key]
        elif isinstance(value,list) and key.isdecimal() and (key=='0' or not key.startswith('0')): value=value[int(key)]
        else: raise KeyError(path)
    return value


def extract(route, body):
    result={}
    for name, field in route['event_schema'].items():
        if field.get('source') != 'body' or field.get('trust','payload') != 'payload':
            raise ValueError('unsupported_extraction')
        try: value=pointer(body,field['pointer'])
        except (KeyError,IndexError):
            if field.get('required',True): raise ValueError('missing_field')
            continue
        typed(value,field)
        result[name]=value
    return result


class RunClient:
    def __init__(self, targets):
        self.targets=targets
        for config in targets.values():
            allowed={'url','token_env','principal','verified','fallback_disabled','models','allow_loopback_http'}
            if not isinstance(config,dict) or set(config)-allowed: raise ValueError('unsupported_execution_target_setting')

    def validate_target(self,target):
        config=self.targets[target]
        if config.get('verified') is not True: raise ValueError('unverified_execution_target')
        url=urlparse(config['url'])
        if url.username or url.password or url.query or url.fragment: raise ValueError('invalid_target')
        if url.scheme!='https' and not (config.get('allow_loopback_http') and url.scheme=='http' and url.hostname in ('localhost','127.0.0.1','::1')): raise ValueError('tls_required')
        if not os.environ.get(config['token_env']): raise ValueError('missing_target_credentials')
        if config.get('fallback_disabled') is not True: raise ValueError('fallback_unverified')
        if not isinstance(config.get('principal'),str) or not config['principal']: raise ValueError('invalid_principal')
        return config

    def preflight(self, selection, target):
        config=self.validate_target(target)
        models=config['models']; model=selection['model']
        supported=models.get(model)
        if not supported or supported['provider']!=selection['provider']: raise ValueError('unsupported_model')
        if selection.get('effort') is not None and selection['effort'] not in supported.get('efforts',[]): raise ValueError('unsupported_effort')
        if selection.get('allowed_toolsets') is not None: raise ValueError('unsupported_toolsets')
        if config.get('fallback_disabled') is not True: raise ValueError('fallback_unverified')
        return config['principal']

    async def _call(self, target, method, path, body=None, key=None):
        config=self.targets[target]
        headers={'Authorization':'Bearer '+os.environ[config['token_env']]}
        if key: headers['Idempotency-Key']=key
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as session:
            async with session.request(method,config['url'].rstrip('/')+path,headers=headers,json=body,allow_redirects=False) as response:
                if response.status>=400 or 300<=response.status<400:
                    if response.status==404 and path.startswith('/v1/runs/') and (method=='GET' or path.endswith('/stop')): raise HostRunUnavailable('host_run_unavailable')
                    if method=='POST' and path=='/v1/runs' and 400<=response.status<500 and response.status not in (408,409,429): raise LaunchRejected('host_rejected')
                    raise RuntimeError('host_unavailable')
                raw=await response.content.read(1024*1024+1)
                if len(raw)>1024*1024: raise ValueError('host_response_too_large')
                return json.loads(raw)

    async def submit(self,payload,key,target): return await self._call(target,'POST','/v1/runs',payload,key)
    async def status(self,run_id,target): return await self._call(target,'GET','/v1/runs/'+quote(run_id,safe=''))
    async def cancel(self,run_id,target): return await self._call(target,'POST','/v1/runs/'+quote(run_id,safe='')+'/stop',{})


class WebhookService:
    def __init__(self, registry, resolver, deployment, ledger, *, host=None):
        validate_routes(registry,deployment)
        self.registry=registry; self.resolver=resolver; self.deployment=deployment; self.ledger=ledger
        self.host=host or RunClient(deployment.get('targets',{})); self.tasks=set(); self.reconciler=None; self.owners={}; self.jobs={}
        self.routes={route['id']:route for route in self.config.get('webhooks',[])}
        for auth in deployment.get('auth_profiles',{}).values():
            if not isinstance(auth,dict) or set(auth)-{'scope','principal','secret_env','signature_header'}: raise ValueError('unsupported_auth_protocol')
        scopes=set()
        for route in self.routes.values():
            auth=deployment.get('auth_profiles',{}).get(route.get('auth_profile'),{})
            scope=route.get('security_scope',auth.get('scope'))
            if not isinstance(scope,str) or not scope or scope in scopes: raise ValueError('invalid_or_duplicate_route_security_scope')
            scopes.add(scope)
            if 'path' in route and route['path']!='/orpheus/webhooks/'+route['id']: raise ValueError('unsupported_route_path')
            if 'filters' in route: Registry._predicate(route['filters'],{k:route['event_schema'][k] for k in route['routing_fields']})

    @property
    def config(self):
        for name in ('config','raw','source','data'):
            value=getattr(self.registry,name,None)
            if isinstance(value,dict): return value
        if isinstance(self.registry,dict): return self.registry
        raise ValueError('registry_snapshot_unavailable')

    def _task(self,coro):
        task=asyncio.create_task(coro); self.tasks.add(task); task.add_done_callback(self.tasks.discard)

    def _reject(self,status,reason,scope=None):
        self.ledger.audit(scope,reason)
        return web.json_response({'outcome':'rejected','reason':reason},status=status)

    async def ingress(self,request):
        route=self.routes.get(request.match_info['route'])
        if not route: return self._reject(404,'unknown_route')
        auth=self.deployment.get('auth_profiles',{}).get(route['auth_profile'])
        if not auth or not auth.get('scope') or route.get('receipt',{}).get('kind')!='disabled': return self._reject(503,'route_unavailable')
        scope=route.get('security_scope',auth['scope']); secret=os.environ.get(auth.get('secret_env',''))
        try:
            if not getattr(self.registry,'admissions_enabled',True): raise ValueError('registry_stale')
            if route.get('policy') in getattr(self.registry,'unavailable_policies',{}): raise ValueError('policy_unavailable')
            if hasattr(self.host,'validate_target'): self.host.validate_target(route['execution_target'])
        except (ValueError,KeyError,TypeError): return self._reject(503,'route_unavailable',scope)
        if not secret: return self._reject(503,'route_unavailable',scope)
        try: raw=await request.read()
        except web.HTTPRequestEntityTooLarge: return self._reject(413,'body_size',scope)
        if len(raw)>65536: return self._reject(413,'body_size',scope)
        signature=request.headers.get(auth.get('signature_header','X-Hub-Signature-256'),'')
        expected='sha256='+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature.encode('utf-8'),expected.encode('ascii')): return self._reject(401,'authentication',scope)
        if request.content_type!='application/json': return self._reject(400,'content_type',scope)
        try:
            body=json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
            if not isinstance(body,dict): raise ValueError('body_object')
            values=extract(route,body)
            if 'filters' in route and not matches(route['filters'],{k:v for k,v in values.items() if k in route['routing_fields']}): return self._reject(200,'filtered',scope)
            task='\n'.join(name+': '+json.dumps(values[name],ensure_ascii=False) for name in route['task_fields'] if name in values)
            if not task.strip(): return self._reject(400,'empty_task',scope)
            target=route['execution_target']; target_config=self.deployment['targets'][target]
            snapshot={'route_id':route['id'],'registry_snapshot':self.config,'task':task,'context':values,
                      'target':target,'target_snapshot':target_config,'principal':target_config['principal'],'receipt':'skipped'}
            row,new=self.ledger.reserve(scope,hashlib.sha256(raw).hexdigest(),snapshot)
        except Conflict: return self._reject(409,'identity_body_conflict',scope)
        except (ValueError,KeyError,TypeError): return self._reject(400,'invalid_input',scope)
        if new: self.schedule(row)
        return web.json_response({'request_id':row['id'],'state':row['state']},status=202 if new else 200)

    def schedule(self,row):
        rid=row['id']
        if rid in self.jobs: return
        self.owners[rid]=row['generation']
        operation=self.process(row) if row['state'] in ('resolving','selected') else self.observe(row)
        task=asyncio.create_task(operation); self.jobs[rid]=task; self.tasks.add(task)
        def finished(done):
            self.tasks.discard(done); self.jobs.pop(rid,None)
            if not done.cancelled(): done.exception()
        task.add_done_callback(finished)

    async def process(self,row):
        rid=row['id']; generation=row['generation']
        try:
            if row.get('target_snapshot',self.deployment['targets'].get(row['target']))!=self.deployment['targets'].get(row['target']): raise ValueError('target_changed')
            if row['state']=='resolving':
                # Restart recovery must resolve against the exact durable snapshot.
                resolver=self.resolver
                if row['registry_snapshot']!=self.config:
                    registry=type(self.registry).from_dict(row['registry_snapshot'])
                    resolver=type(self.resolver)(registry,systemone_client=getattr(self.resolver,'systemone_client',None))
                selection=await asyncio.wait_for(resolver.resolve('webhook',row['task'],context=row['context'],route_id=row['route_id']),45)
                self.host.preflight(selection,row['target'])
                if not self.ledger.change(rid,generation,('resolving',),'selected',selection=selection): return
                row=self.ledger.get(rid)
            if row['state']=='selected':
                selected=row['selection']; principal=self.host.preflight(selected,row['target'])
                if principal!=row['principal']: raise ValueError('target_principal_changed')
                payload={'input':row['task'],'model':selected['model'],'provider':selected['provider']}
                if selected.get('effort') is not None: payload['model_options']={'reasoning_effort':selected['effort']}
                if selected.get('instructions'): payload['instructions']=selected['instructions']
                key='orpheus-'+rid
                token=uuid.uuid4().hex
                payload_digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
                if not self.ledger.change(rid,generation,('selected',),'starting',payload=payload,idempotency_key=key,payload_digest=payload_digest,dispatch_token=token): return
                try: response=await self.host.submit(payload,key,row['target'])
                except LaunchRejected:
                    self.ledger.change(rid,generation,('starting',),'failed',error={'phase':'launch','code':'host_rejected'}); return
                except Exception:
                    self.ledger.change(rid,generation,('starting',),'unknown',error={'phase':'launch','code':'ambiguous_acceptance'}); return
                host_id=response.get('run_id') or response.get('id')
                if not isinstance(host_id,str) or not host_id:
                    self.ledger.change(rid,generation,('starting',),'unknown'); return
                try:
                    published=self.ledger.publish_acceptance(rid,token,key,payload_digest,host_id)
                except Exception:
                    logger.exception('Unable to persist accepted host run %s for request %s; operator reconciliation required',host_id,rid)
                    raise
                if not published:
                    logger.error('Dispatch acceptance publication conflict for request %s host run %s; durable receipt requires reconciliation',rid,host_id)
        except asyncio.CancelledError: raise
        except Exception:
            self.ledger.change(rid,generation,('resolving','selected'),'failed',error={'phase':'selection','code':'selection_or_capability_error'})

    async def observe(self,row):
        explicit=row.get('_explicit',False)
        if row.get('disposition')=='abandoned' and not explicit: return
        if row['state'] in ('completed','failed','cancelled'): return
        if not row.get('host_id'):
            if row['state']=='starting' and row.get('_recovered'): self.ledger.change(row['id'],row['generation'],('starting',),'unknown')
            return
        target=self.deployment['targets'].get(row['target'],{})
        original=row.get('target_snapshot',target)
        if target.get('principal')!=row['principal'] or target.get('url','').rstrip('/')!=original.get('url','').rstrip('/'):
            self.ledger.change(row['id'],row['generation'],('running','starting','unknown'),'unknown',error={'phase':'observation','code':'target_identity_changed'})
            return
        try:
            if row.get('cancel_requested'): await self.host.cancel(row['host_id'],row['target'])
            result=await self.host.status(row['host_id'],row['target'])
        except HostRunUnavailable:
            self.ledger.change(row['id'],row['generation'],('running','starting','unknown'),'unknown',error={'phase':'observation','code':'host_run_unavailable'},result_availability='unavailable')
            return
        except Exception: return
        status=result.get('status'); mapping={'queued':'running','running':'running','stopping':'running','completed':'completed','failed':'failed','cancelled':'cancelled','interrupted':'failed','unknown':'unknown'}
        state=mapping.get(status)
        if not state: return
        updates={'native_status':status}
        runtime=result.get('runtime')
        if isinstance(runtime,dict):
            observed={key:runtime[key] for key in ('model','provider') if isinstance(runtime.get(key),str)}
            if observed:
                updates['observed']={'final_runtime':observed,'source':'host_run_status.runtime','effort':None,'coverage':'final_pair_only','acquired_at':time.time()}
        if status=='interrupted': updates['error']={'phase':'execution','code':'interrupted'}
        output=result.get('output') if row.get('disposition')!='abandoned' else None
        if output is not None:
            output=output if isinstance(output,str) else json.dumps(output,ensure_ascii=False)
            for secret in self.deployment.get('redact_literals',[]): output=output.replace(secret,'[REDACTED]')
            encoded=output.encode(); updates.update(result=encoded[:262144].decode(errors='ignore'),truncated=len(encoded)>262144,result_bytes=len(encoded),result_availability='available',result_observed=time.time())
            if state in ('completed','failed','cancelled'): updates['result_expires']=time.time()+7*86400
        elif state in ('completed','failed','cancelled'):
            if 'result' in row:
                updates.update(result_availability='available',result_expires=time.time()+7*86400,result_is_partial=True)
            else: updates['result_availability']='unavailable'
        self.ledger.change(row['id'],row['generation'],('running','starting','unknown'),state,**updates)

    def authorize(self,request,row):
        value=request.headers.get('Authorization','')
        if not value.startswith('Bearer '): return False
        supplied=value[7:]
        return any(os.environ.get(env) and hmac.compare_digest(supplied.encode('utf-8'),os.environ[env].encode('utf-8')) and row['scope'] in scopes for env,scopes in self.deployment.get('operators',{}).items())

    async def operator(self,request):
        row=self.ledger.get(request.match_info['id'])
        if not row or not self.authorize(request,row): return self._reject(403,'operator_authorization')
        action=request.match_info.get('action')
        if action=='cancel':
            row=self.ledger.cancel(row['id']); self.ledger.audit(row['scope'],'operator_cancel')
            if row.get('host_id'):
                row=self.ledger.claim(row['id']) or row
                await self.observe(dict(row,_explicit=True))
        elif action=='reconcile':
            self.ledger.audit(row['scope'],'operator_reconcile')
            try:
                options=await request.json() if request.can_read_body else {}
            except (ValueError,TypeError): return self._reject(400,'invalid_input',row['scope'])
            if not isinstance(options,dict) or set(options)-{'disposition'}: return self._reject(400,'unsupported_reconciliation',row['scope'])
            if options:
                if options.get('disposition')!='abandoned' or not self.ledger.abandon(row['id']): return self._reject(409,'invalid_disposition',row['scope'])
            else:
                claimed=self.ledger.claim(row['id'])
                if claimed: row=dict(claimed,_recovered=True)
                await self.observe(dict(row,_explicit=True))
        elif action is not None: return self._reject(404,'unknown_action')
        row=self.ledger.get(row['id'])
        # Internal snapshot, route credentials and submitted body are never exposed.
        fields=('id','state','selection','host_id','observed','launch_accepted','result','result_availability','result_is_partial','result_expires','result_observed','truncated','result_bytes','cancel_requested','native_status','error','disposition')
        return web.json_response({k:row[k] for k in fields if k in row})

    async def reconcile(self):
        while True:
            try:
                rows=self.ledger.active()
                active_ids={row['id'] for row in rows}
                self.owners={rid:generation for rid,generation in self.owners.items() if rid in active_ids}
            except Exception:
                logger.exception('Unable to read active webhook ledger; retrying')
                rows=[]
            for previous in rows:
                try:
                    rid=previous['id']
                    # Only our matching-generation dispatcher is known to have ended.
                    # A live local job or another process's unexpired lease stays owned.
                    if (self.owners.get(rid)==previous['generation'] and rid not in self.jobs
                            and previous['state']=='starting' and not previous.get('host_id')):
                        if self.ledger.change(rid,previous['generation'],('starting',),'unknown',error={'phase':'launch','code':'dispatch_completion_unconfirmed'}):
                            self.owners.pop(rid,None)
                            continue
                    if self.owners.get(rid)==previous['generation'] and self.ledger.renew(rid,previous['generation']):
                        row=previous
                    else:
                        claimed=self.ledger.claim(rid)
                        row=dict(claimed,_recovered=True) if claimed else None
                    if row: self.schedule(row)
                except Exception:
                    logger.exception('Unable to reconcile webhook request %s; retrying',previous.get('id'))
            try: self.ledger.expire_results()
            except Exception: logger.exception('Unable to compact webhook ledger; retrying')
            await asyncio.sleep(10)

    async def start(self,app): self.reconciler=asyncio.create_task(self.reconcile())
    async def close(self,app):
        tasks=list(self.tasks)+([self.reconciler] if self.reconciler else [])
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        self.ledger.close()

    def mount(self,app):
        app.router.add_post('/orpheus/webhooks/{route}',self.ingress)
        app.router.add_get('/orpheus/requests/{id}',self.operator)
        app.router.add_post('/orpheus/requests/{id}/{action}',self.operator)
        app.on_startup.append(self.start); app.on_cleanup.append(self.close)


def create_platform_handler(registry,resolver,deployment,state_dir):
    def factory(app,adapter=None):
        directory=Path(state_dir); secure_state_directory(directory)
        service=WebhookService(registry,resolver,deployment,Ledger(directory/'webhooks.sqlite3'))
        service.mount(app)
        return service
    return factory
