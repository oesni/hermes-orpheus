"""Entrypoint-bound, finite tuple resolution without implicit reselection."""
import asyncio
import copy
import json
import time
import uuid
from .config import ConfigError, digest, typed


class SelectionError(ValueError):
    def __init__(self, message, code='invalid_selection'):
        super().__init__(message)
        self.code=code


def matches(predicate, values):
    if 'all' in predicate: return all(matches(p,values) for p in predicate['all'])
    if 'any' in predicate: return any(matches(p,values) for p in predicate['any'])
    if 'not' in predicate: return not matches(predicate['not'],values)
    field,op=predicate['field'],predicate['op']
    if op=='exists': return field in values
    if field not in values: return False
    value,expected=values[field],predicate['value']
    if op=='eq': return type(value) is type(expected) and value==expected
    if op=='in': return any(type(value) is type(v) and value==v for v in expected)
    return expected in value


class Resolver:
    def __init__(self, registry, jev_client=None):
        self.registry=registry
        self.jev_client=jev_client

    async def resolve(self, entrypoint, task, context=None, preset_id=None, proposals=None, route_id=None):
        registry=copy.deepcopy(self.registry)
        if not registry.admissions_enabled: raise SelectionError('Registry source stale','stale_preset')
        if entrypoint not in ('subagent','webhook'): raise SelectionError('Invalid entrypoint')
        if not isinstance(task,str) or not task.strip() or len(task)>65536: raise SelectionError('Invalid task','invalid_input')
        context={} if context is None else context
        if not isinstance(context,dict): raise SelectionError('Invalid context','invalid_input')
        route=None
        if entrypoint=='subagent':
            if route_id is not None: raise SelectionError('Route forbidden for subagent')
            policy_id=registry.subagent_policy
        else:
            route=registry.webhooks.get(route_id)
            if not route: raise SelectionError('Unknown route','route_unavailable')
            policy_id=route['policy']
        if policy_id not in registry.policies: raise SelectionError('Policy unavailable','policy_unavailable')
        policy=registry.policies[policy_id]
        if policy['entrypoint']!=entrypoint: raise SelectionError('Entrypoint mismatch')
        if preset_id is not None and policy['preset_selector']['kind']!='parent': raise SelectionError('Preset proposal forbidden')
        if proposals is not None and policy['field_resolver']['kind']!='parent': raise SelectionError('Field proposals forbidden')
        if entrypoint=='subagent':
            schema=policy['input_schema']
            values={'task.text':task}
            for key,value in context.items():
                if not isinstance(key,str) or '.' in key: raise SelectionError('Nested context forbidden','invalid_input')
                values['context.'+key]=value
        else:
            schema=route['event_schema']
            values=dict(context)
            if 'event' in values and isinstance(values['event'],dict):
                event=values.pop('event'); values.update({'event.'+k:v for k,v in event.items()})
        if set(values)-set(schema): raise SelectionError('Undeclared context','invalid_input')
        try:
            for field,spec in schema.items():
                if field not in values:
                    if spec.get('required',entrypoint=='webhook'): raise SelectionError('Required input missing','invalid_input')
                else: typed(values[field],spec)
        except ConfigError as exc: raise SelectionError(str(exc),exc.code) from exc
        projection_scope=set(schema)
        if route: projection_scope &= set(route['routing_fields'])|set(route['task_fields'])
        rule_values={name:value for name,value in values.items() if route is None or name in route['routing_fields']}
        attempts=[]
        selected=None
        deadline=time.monotonic()+45
        async def run(node,stage):
            nonlocal selected
            if time.monotonic()>=deadline: raise SelectionError('Selection deadline exceeded','timeout')
            kind=node['kind']
            if kind=='parent' and entrypoint!='subagent': raise SelectionError('Parent forbidden')
            candidates=registry.presets if stage=='preset' else selected['compatible_settings']
            try:
                if kind=='parent':
                    if stage=='preset':
                        if not isinstance(preset_id,str): raise SelectionError('Parent preset ID required')
                        result=preset_id
                    else:
                        if proposals is None: proposal={}
                        elif not isinstance(proposals,dict): raise SelectionError('Proposals must be an object')
                        else: proposal=proposals
                        if set(proposal)-set(selected['fields']): raise SelectionError('Unknown proposed field')
                        for name,field in selected['fields'].items():
                            if field['mode']=='fixed' and name in proposal and proposal[name]!=field['value']: raise SelectionError('Fixed value override')
                        matching=[]
                        for name,settings in candidates.items():
                            full={k:f['value'] for k,f in selected['fields'].items() if f['mode']=='fixed'}; full.update(settings)
                            if all(full.get(k)==v for k,v in proposal.items()): matching.append(name)
                        if len(matching)!=1: raise SelectionError('Parent must select one complete tuple')
                        result=matching[0]
                elif kind=='fixed': result=node['preset' if stage=='preset' else 'settings']
                elif kind=='rules':
                    result=None
                    for rule in sorted(node['rules'],key=lambda r:r['priority']):
                        if matches(rule['when'],rule_values):
                            result=rule['preset' if stage=='preset' else 'settings']
                            attempts.append({'node':node['id'],'rule':rule['id']}); break
                    if result is None:
                        no=node.get('no_match',{'kind':'error'})
                        if no['kind']=='fixed': result=no['preset' if stage=='preset' else 'settings']
                        elif no['kind']=='resolver':
                            attempts.append({'node':node['id'],'cause':'no_match','target':no['target']})
                            return await run(policy['resolver_nodes'][no['target']],stage)
                        else: raise SelectionError('No rule matched','no_match')
                elif kind=='systemone':
                    if self.jev_client is None: raise SelectionError('System One credentials unavailable','missing_credentials')
                    allowed=set(node.get('projection_fields',[])) & projection_scope
                    if set(node.get('required_fields',[]))-allowed or any(f not in values for f in node.get('required_fields',[])): raise SelectionError('Required System One projection excluded')
                    state={k:values[k] for k in sorted(allowed) if k in values}
                    choices={}
                    for candidate_id,candidate in sorted(candidates.items()):
                        if stage=='preset':
                            description={'purpose':candidate.get('purpose',''),'guidance':candidate.get('guidance','')}
                        else:
                            settings={k:f['value'] for k,f in selected['fields'].items() if f['mode']=='fixed'}
                            settings.update(candidate)
                            inventory_model=registry.inventory[settings['model']]
                            settings.update(model=inventory_model['model'],provider=inventory_model['provider'])
                            description={'purpose':selected.get('purpose',''),'guidance':selected.get('guidance',''),'settings':settings}
                        choices[candidate_id]=json.dumps(description,sort_keys=True,separators=(',',':'))
                    timeout=min(node.get('timeout',10),deadline-time.monotonic())
                    for attempt in range(node.get('retries',0)+1):
                        try:
                            answer=await asyncio.wait_for(self.jev_client.choose(model=node['model'], state=state, choices=choices, timeout=timeout, min_confidence=node.get('min_confidence')),timeout)
                            result=answer.get('choice') if isinstance(answer,dict) else answer
                            if node.get('min_confidence') is not None:
                                confidence=answer.get('confidence') if isinstance(answer,dict) else None
                                if type(confidence) not in (int,float) or not 0<=confidence<=1: raise SelectionError('Missing or invalid confidence','invalid_response')
                                if confidence<node['min_confidence']: raise SelectionError('Low confidence','low_confidence')
                            break
                        except asyncio.TimeoutError as exc:
                            if attempt==node.get('retries',0): raise SelectionError('System One timed out','timeout') from exc
                        except SelectionError as exc:
                            if exc.code not in ('timeout','rate_limited','service_unavailable') or attempt==node.get('retries',0): raise
                        timeout=min(node.get('timeout',10),deadline-time.monotonic())
                        if timeout<=0: raise SelectionError('Selection deadline exceeded','timeout')
                else: raise SelectionError('Unsupported resolver')
                if not isinstance(result,str) or result not in candidates: raise SelectionError('Choice outside pending candidates','invalid_response' if kind=='systemone' else 'invalid_selection')
                attempts.append({'node':node['id'],'result':result})
                return result
            except SelectionError as exc:
                for edge in node.get('on_error',[]):
                    if exc.code in edge['errors']:
                        attempts.append({'node':node['id'],'edge':edge['id'],'cause':exc.code,'target':edge['target']})
                        return await run(policy['resolver_nodes'][edge['target']],stage)
                raise
        chosen=await run(policy['preset_selector'],'preset')
        selected=registry.presets[chosen]
        tuple_id=await run(policy['field_resolver'],'field')
        resolved={k:f['value'] for k,f in selected['fields'].items() if f['mode']=='fixed'}
        resolved.update(selected['compatible_settings'][tuple_id])
        model_ref=resolved['model']; model=registry.inventory[model_ref]
        resolved.update(model=model['model'],provider=model['provider'])
        return copy.deepcopy(dict(request_id=str(uuid.uuid4()),entrypoint=entrypoint,policy_id=policy_id,policy_revision=policy['revision'],registry_revision=registry.revision,preset_id=chosen,preset_revision=selected['revision'],tuple_id=tuple_id,model_ref=model_ref,candidate_set_hash=digest(selected['compatible_settings']),requested={'preset_id':preset_id,'proposals':proposals},resolved=resolved,attempts=attempts,created_at=time.time(),**resolved))
