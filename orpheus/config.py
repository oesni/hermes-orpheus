"""Strict, independently quarantined configuration snapshots."""
from __future__ import annotations
import copy
import hashlib
import json
from collections import Counter
from typing import Any
import yaml
from .session import SESSION_FIELDS


class ConfigError(ValueError):
    def __init__(self, message, code='invalid_config'):
        super().__init__(message)
        self.code = code


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def keys(obj, allowed, required=()):
    if not isinstance(obj, dict) or set(obj) - set(allowed) or set(required) - set(obj):
        raise ConfigError('Invalid or unknown configuration keys')


def string_list(value, label, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value) or any(not isinstance(x, str) or not x for x in value) or len(set(value)) != len(value):
        raise ConfigError(f'Invalid {label}')


def input_schema(schema, webhook=False):
    if not isinstance(schema, dict): raise ConfigError('Input schema must be a mapping')
    for name, spec in schema.items():
        if not isinstance(name, str) or not name: raise ConfigError('Invalid input path')
        if webhook and name in SESSION_FIELDS: raise ConfigError('Session fields are subagent-only')
        keys(spec, {'type','max_length','max_items','required','trust','values','source','pointer','header'} if webhook else {'type','max_length','max_items','required','trust','values'}, {'type'})
        kind=spec['type']
        if not isinstance(kind,str) or kind not in ('string','string_list','number','boolean','enum'): raise ConfigError('Invalid input type')
        if 'required' in spec and type(spec['required']) is not bool: raise ConfigError('required must be boolean')
        if spec.get('trust','payload') not in ('payload','verified_metadata'): raise ConfigError('Invalid input trust')
        for bound in ('max_length','max_items'):
            if bound in spec and (type(spec[bound]) is not int or not 1<=spec[bound]<=65536): raise ConfigError('Invalid input bound')
        if 'max_items' in spec and kind!='string_list': raise ConfigError('max_items requires string_list')
        if 'max_length' in spec and kind not in ('string','string_list','enum'): raise ConfigError('max_length requires string input')
        if kind=='enum': string_list(spec.get('values'),'enum values',True)
        elif 'values' in spec: raise ConfigError('values requires enum')
        if webhook:
            if spec.get('source')!='body': raise ConfigError('Only body extraction is supported')
            if spec.get('trust','payload')!='payload': raise ConfigError('Verified metadata extraction is unsupported')
            if 'header' in spec: raise ConfigError('Header extraction is unsupported')
            key='pointer' if spec['source']=='body' else 'header'
            if not isinstance(spec.get(key),str): raise ConfigError('Missing extraction location')
            if key=='pointer' and spec[key] and not spec[key].startswith('/'): raise ConfigError('Invalid JSON pointer')
            if key=='header' and not spec[key]: raise ConfigError('Invalid header name')
        elif name in SESSION_FIELDS:
            # Host-observed calling-session metadata: never caller supplied, so it must be
            # declared as verified metadata and stays optional (it is unknown before the first
            # model response of a session).
            if spec.get('trust')!='verified_metadata' or kind!='string' or spec.get('required',False):
                raise ConfigError('Session fields must be optional verified_metadata strings')
        elif (name!='task.text' and (not name.startswith('context.') or name.count('.')!=1)) or spec.get('trust','payload')!='payload':
            raise ConfigError('Invalid subagent input path or trust')


def typed(value, spec):
    kind = spec.get('type')
    valid = {'string': lambda: isinstance(value, str), 'number': lambda: type(value) in (int, float), 'boolean': lambda: type(value) is bool,
             'string_list': lambda: isinstance(value, list) and all(isinstance(x, str) for x in value), 'enum': lambda: value in spec.get('values', []) and any(type(value) is type(x) for x in spec.get('values', []))}
    if kind not in valid or not valid[kind]():
        raise ConfigError('Input has invalid type', 'invalid_input')
    if isinstance(value, (str, list)) and len(value) > spec.get('max_items' if isinstance(value, list) else 'max_length', 16384):
        raise ConfigError('Input exceeds bound', 'invalid_input')
    if isinstance(value, list) and any(len(x) > spec.get('max_length', 16384) for x in value):
        raise ConfigError('Input exceeds bound', 'invalid_input')
    if type(value) in (int, float):
        import math
        if not math.isfinite(value):
            raise ConfigError('Nonfinite number', 'invalid_input')


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key, value in node.value:
        name = loader.construct_object(key, deep=deep)
        if not isinstance(name, str) or name in result:
            raise ConfigError('Duplicate or non-string YAML key')
        result[name] = loader.construct_object(value, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


class Registry:
    @classmethod
    def from_yaml(cls, text):
        try:
            return cls.from_dict(yaml.load(text, Loader=UniqueLoader))
        except yaml.YAMLError as exc:
            raise ConfigError('Invalid YAML') from exc

    @classmethod
    def from_dict(cls, config):
        return cls(config)

    def __init__(self, config):
        config = copy.deepcopy(config)
        keys(config, {'schema_version','inventory','presets','policies','subagent_policy','webhooks','auth_profiles','execution_targets','operators','storage'}, {'schema_version','inventory','presets','policies'})
        if type(config['schema_version']) is not int or config['schema_version'] != 1:
            raise ConfigError('Unsupported schema version')
        self.source = config
        try: self.revision = digest(config)
        except (TypeError, ValueError, RecursionError) as exc: raise ConfigError('Configuration must contain finite JSON values') from exc
        self.admissions_enabled = True
        keys(config['inventory'], {'models'}, {'models'})
        self.inventory = config['inventory']['models']
        if not isinstance(self.inventory, dict):
            raise ConfigError('Models must be a mapping')
        for ref, model in self.inventory.items():
            keys(model, {'provider','model','efforts'}, {'provider','model'})
            if not isinstance(ref, str) or not all(isinstance(model[k], str) and model[k] for k in ('provider','model')):
                raise ConfigError('Invalid model identity')
            if 'efforts' in model and (not isinstance(model['efforts'], list) or not model['efforts'] or any(not isinstance(x,str) for x in model['efforts']) or len(set(model['efforts'])) != len(model['efforts'])):
                raise ConfigError('Invalid efforts')
        if not isinstance(config['presets'], list):
            raise ConfigError('Presets must be a list')
        self.presets, self.quarantined = {}, {}
        counts = Counter(p.get('id') for p in config['presets'] if isinstance(p,dict) and isinstance(p.get('id'),str))
        for index, preset in enumerate(config['presets']):
            name = preset.get('id', f'invalid-{index}') if isinstance(preset,dict) else f'invalid-{index}'
            if not isinstance(name,str): name = f'invalid-{index}'
            try:
                if counts[name] > 1: raise ConfigError('Duplicate preset ID')
                self._preset(preset)
                self.presets[name] = dict(preset, revision=digest(preset))
            except (ConfigError, TypeError, ValueError) as exc:
                self.quarantined[name] = str(exc)
        self.policies, self.unavailable_policies = {}, {}
        self.webhooks = {}
        routes = config.get('webhooks', [])
        if not isinstance(routes,list): raise ConfigError('webhooks must be a list')
        for route in routes:
            keys(route, {'id','path','policy','auth_profile','execution_target','event_schema','routing_fields','task_fields','receipt','filters','security_scope'}, {'id','policy','auth_profile','execution_target','receipt','event_schema','routing_fields','task_fields'})
            for field in ('id','policy','auth_profile','execution_target'):
                if not isinstance(route[field],str) or not route[field]: raise ConfigError('Invalid route reference')
            if 'path' in route and (not isinstance(route['path'],str) or route['path'] != '/orpheus/webhooks/'+route['id']): raise ConfigError('Invalid route path')
            keys(route['receipt'],{'kind'},{'kind'})
            if route['receipt']['kind']!='disabled': raise ConfigError('Receipt adapter unsupported')
            input_schema(route['event_schema'],True)
            for field in ('routing_fields','task_fields'):
                string_list(route[field],field,nonempty=field=='task_fields')
                if set(route[field])-set(route['event_schema']): raise ConfigError('Unknown route input field')
            if 'filters' in route: self._predicate(route['filters'],{name:route['event_schema'][name] for name in route['routing_fields']})
            if route['id'] in self.webhooks: raise ConfigError('Duplicate route ID')
            self.webhooks[route['id']] = route
        if not isinstance(config['policies'],dict): raise ConfigError('Policies must be a mapping')
        for name, policy in config['policies'].items():
            try:
                self._policy(policy)
                compiled = copy.deepcopy(policy)
                # Keep source/revision tied to the operator's exact configuration.
                for node in [compiled['preset_selector'], compiled['field_resolver'],
                             *compiled.get('resolver_nodes', {}).values()]:
                    if node['kind'] == 'jev':
                        node['kind'] = 'systemone'
                self.policies[name] = dict(compiled, revision=digest(policy))
            except (ConfigError, TypeError, ValueError, KeyError) as exc:
                self.unavailable_policies[name] = str(exc)
        self.subagent_policy = config.get('subagent_policy')
        if self.subagent_policy is not None:
            if not isinstance(self.subagent_policy,str) or self.subagent_policy not in config['policies']:
                raise ConfigError('Unknown subagent policy binding')
            bound=config['policies'][self.subagent_policy]
            if isinstance(bound,dict) and bound.get('entrypoint')!='subagent':
                raise ConfigError('Subagent policy binding must target subagent entrypoint')
        self.unavailable_routes={}
        for route in self.webhooks.values():
            if route['policy'] not in config['policies']:
                raise ConfigError('Unknown webhook policy binding')
            definition=config['policies'][route['policy']]
            if isinstance(definition,dict) and definition.get('entrypoint')!='webhook':
                raise ConfigError('Webhook policy binding must target webhook entrypoint')
            if route['policy'] not in self.policies:
                self.unavailable_routes[route['id']]=self.unavailable_policies.get(route['policy'],'Policy unavailable')

    def _preset(self, preset):
        keys(preset, {'id','purpose','guidance','fields','compatible_settings'}, {'id','fields','compatible_settings'})
        for field in ('purpose','guidance'):
            if field in preset and (not isinstance(preset[field],str) or len(preset[field])>16384): raise ConfigError('Invalid preset description')
        if not isinstance(preset['id'],str) or not preset['id']: raise ConfigError('Missing preset ID')
        fields = preset['fields']
        keys(fields, {'model','effort','instructions','allowed_toolsets'}, {'model'})
        for name, field in fields.items():
            keys(field, {'mode','value','candidates'}, {'mode'})
            if field['mode'] == 'fixed':
                if set(field) != {'mode','value'}: raise ConfigError('Fixed field requires only value')
                values = [field['value']]
            elif field['mode'] == 'enum':
                if name in ('instructions','allowed_toolsets'): raise ConfigError('Instructions and tools must be fixed')
                values = field.get('candidates')
                if set(field) != {'mode','candidates'} or not isinstance(values,list) or not values or len({digest(v) for v in values}) != len(values): raise ConfigError('Invalid enum')
            else: raise ConfigError('Unsupported field mode')
            for value in values:
                if name == 'allowed_toolsets':
                    if not isinstance(value,list) or not value or any(not isinstance(x,str) or not x for x in value): raise ConfigError('Empty/invalid toolsets unsupported')
                elif not isinstance(value,str) or not value: raise ConfigError('Invalid field value')
                if name == 'model' and value not in self.inventory: raise ConfigError('Unknown inventory model')
        tuples = preset['compatible_settings']
        if not isinstance(tuples,dict) or not tuples: raise ConfigError('Complete compatible tuples required')
        dynamic = {name for name,f in fields.items() if f['mode'] == 'enum'}
        for name, values in tuples.items():
            if not isinstance(name,str) or not name: raise ConfigError('Invalid tuple ID')
            keys(values, set(fields), dynamic)
            merged = {k:f['value'] for k,f in fields.items() if f['mode']=='fixed'}
            merged.update(values)
            for key,value in merged.items():
                f = fields[key]
                if value not in ([f['value']] if f['mode']=='fixed' else f['candidates']): raise ConfigError('Tuple violates field constraint')
            model = self.inventory[merged['model']]
            if 'effort' in merged and merged['effort'] not in model.get('efforts',[]): raise ConfigError('Unsupported model effort')

    def _policy(self, policy):
        keys(policy, {'entrypoint','input_schema','preset_selector','field_resolver','resolver_nodes'}, {'entrypoint','preset_selector','field_resolver'})
        if policy['entrypoint'] not in ('subagent','webhook'): raise ConfigError('Invalid entrypoint')
        schema = policy.get('input_schema',{})
        if policy['entrypoint']=='subagent':
            input_schema(schema)
            if 'task.text' not in schema or schema['task.text']['type']!='string': raise ConfigError('task.text string schema required')
        else:
            if 'input_schema' in policy: raise ConfigError('Webhook input schema belongs to routes')
            matching = [r for r in self.webhooks.values() if r['policy'] in self.source['policies'] and self.source['policies'][r['policy']] == policy]
            schema={}
            for route in matching:
                for name,spec in route['event_schema'].items():
                    if name in schema and schema[name]!=spec: raise ConfigError('Conflicting shared route schemas')
                    schema[name]=spec
        rule_schema=schema
        if policy['entrypoint']=='webhook':
            common_fields=set.intersection(*(set(route['routing_fields']) for route in matching)) if matching else set()
            rule_schema={name:spec for name,spec in schema.items() if name in common_fields}
        nodes = policy.get('resolver_nodes',{})
        if not isinstance(nodes,dict): raise ConfigError('Invalid resolver nodes')
        ids=set()
        reachable=set()
        field_results=set()
        def visit(node, stage, stack):
            keys(node, {'id','kind','on_error','preset','settings','rules','no_match','model','projection_fields','required_fields','timeout','min_confidence','retries'}, {'id','kind'})
            kind='systemone' if node['kind']=='jev' else node['kind']
            if not isinstance(kind,str) or kind not in ('parent','fixed','rules','systemone'): raise ConfigError('Invalid resolver kind')
            result_key='preset' if stage=='preset' else 'settings'
            extra={'parent':set(),'fixed':{result_key},'rules':{'rules','no_match'},'systemone':{'model','projection_fields','required_fields','timeout','min_confidence','retries'}}[kind]
            required={'fixed':{result_key},'rules':{'rules'},'systemone':{'model','projection_fields'},'parent':set()}[kind]
            keys(node, {'id','kind','on_error'}|extra, {'id','kind'}|required)
            if not isinstance(node.get('on_error',[]),list): raise ConfigError('Fallback edges must be a list')
            nid=node['id']
            if nid in stack: raise ConfigError('Resolver cycle')
            if not isinstance(nid,str): raise ConfigError('Invalid node ID')
            kind='systemone' if node['kind']=='jev' else node['kind']
            if kind not in ('parent','fixed','rules','systemone'): raise ConfigError('Invalid resolver kind')
            if kind=='parent' and policy['entrypoint']!='subagent': raise ConfigError('Webhook forbids parent selection')
            def output(n):
                key='preset' if stage=='preset' else 'settings'
                if key not in n or not isinstance(n[key],str): raise ConfigError('Missing literal result')
                (reachable if stage=='preset' else field_results).add(n[key])
            if kind=='fixed': output(node)
            if kind=='parent' and stage=='preset': reachable.update(self.presets)
            if kind=='systemone':
                if not isinstance(node.get('model'),str) or not node['model']: raise ConfigError('System One model required')
                projection=node.get('projection_fields',[])
                string_list(projection,'projection fields')
                string_list(node.get('required_fields',[]),'required fields')
                if any(x not in schema for x in projection): raise ConfigError('Invalid System One projection')
                if any(x not in projection for x in node.get('required_fields',[])): raise ConfigError('Required System One field excluded')
                if stage=='preset': reachable.update(self.presets)
                for key,default,low,high in [('timeout',10,0.01,30),('retries',0,0,3),('min_confidence',0,0,1)]:
                    v=node.get(key,default)
                    if type(v) not in (int,float) or not low<=v<=high or (key=='retries' and type(v) is not int): raise ConfigError('Invalid System One bound')
            if kind=='rules':
                rules=node.get('rules',[])
                if not isinstance(rules,list) or len(rules)>256: raise ConfigError('Rule count exceeded')
                priorities=set()
                rule_ids=set()
                for rule in rules:
                    keys(rule, {'id','priority','when',result_key}, {'id','priority','when',result_key})
                    if not isinstance(rule['id'],str) or not rule['id'] or rule['id'] in rule_ids: raise ConfigError('Invalid or duplicate rule ID')
                    rule_ids.add(rule['id'])
                    if type(rule['priority']) is not int or rule['priority'] in priorities: raise ConfigError('Duplicate/invalid priority')
                    priorities.add(rule['priority']); self._predicate(rule['when'],rule_schema); output(rule)
                no=node.get('no_match',{'kind':'error'})
                keys(no, {'kind',result_key,'target'}, {'kind'})
                if no['kind']=='fixed':
                    keys(no,{'kind',result_key},{'kind',result_key})
                elif no['kind']=='resolver': keys(no,{'kind','target'},{'kind','target'})
                if no.get('kind')=='fixed': output(no)
                elif no.get('kind')=='resolver': edge(no['target'],stage,stack|{nid})
                elif no != {'kind':'error'}: raise ConfigError('Invalid no_match')
            used=set()
            edge_ids=set()
            for fallback in node.get('on_error',[]):
                keys(fallback, {'id','errors','target'}, {'id','errors','target'})
                if not isinstance(fallback['id'],str) or not fallback['id'] or fallback['id'] in edge_ids: raise ConfigError('Invalid or duplicate edge ID')
                edge_ids.add(fallback['id'])
                errors=fallback['errors']
                string_list(errors,'fallback errors',True)
                if not isinstance(errors,list) or not errors or set(errors)-{'timeout','rate_limited','service_unavailable','invalid_response','low_confidence'} or used.intersection(errors): raise ConfigError('Invalid fallback errors')
                used.update(errors); edge(fallback['target'],stage,stack|{nid})
        stages={}
        def edge(target,stage,stack):
            if not isinstance(target,str) or target not in nodes or not isinstance(nodes[target],dict) or nodes[target].get('id')!=target: raise ConfigError('Missing resolver node')
            if target in stages and stages[target]!=stage: raise ConfigError('Mixed-stage resolver')
            stages[target]=stage; visit(nodes[target],stage,stack)
        # IDs must be unique, including unused nodes; unused nodes are rejected.
        all_nodes=[policy['preset_selector'],policy['field_resolver'],*nodes.values()]
        for node in all_nodes:
            if not isinstance(node,dict) or not isinstance(node.get('id'),str) or not node['id']: raise ConfigError('Invalid resolver node ID')
            nid=node['id']
            if nid in ids: raise ConfigError('Duplicate node ID')
            ids.add(nid)
        visit(policy['preset_selector'],'preset',set())
        visit(policy['field_resolver'],'field',set())
        if set(nodes)-set(stages): raise ConfigError('Unreachable resolver node')
        if not reachable or reachable-set(self.presets): raise ConfigError('Unavailable preset reference')
        for preset in reachable:
            if field_results-set(self.presets[preset]['compatible_settings']): raise ConfigError('Tuple reference invalid across reachable presets')
        if any(n['kind'] in ('systemone','jev') for n in all_nodes):
            if len(reachable)>255 or any(len(self.presets[p]['compatible_settings'])>255 for p in reachable): raise ConfigError('System One supports at most 255 choices')

    @staticmethod
    def _predicate(pred,schema,depth=0):
        if depth>8 or not isinstance(pred,dict): raise ConfigError('Predicate nesting exceeded')
        for op in ('all','any','not'):
            if op in pred:
                if set(pred)!={op}: raise ConfigError('Invalid compound predicate')
                children=[pred[op]] if op=='not' else pred[op]
                if not isinstance(children,list) or not children or len(children)>64: raise ConfigError('Invalid predicate children')
                for child in children: Registry._predicate(child,schema,depth+1)
                return
        keys(pred, {'field','op','value'}, {'field','op'})
        if pred['field'] not in schema or pred['op'] not in ('eq','in','contains','exists'): raise ConfigError('Invalid predicate')
        if pred['op']=='exists':
            if 'value' in pred: raise ConfigError('exists has no value')
        elif 'value' not in pred: raise ConfigError('Comparison requires value')
        else:
            spec=schema[pred['field']]
            if pred['op']=='in':
                if not isinstance(pred['value'],list) or not pred['value']: raise ConfigError('in requires list')
                for v in pred['value']: typed(v,spec)
            elif pred['op']=='contains':
                if spec['type'] not in ('string','string_list') or not isinstance(pred['value'],str): raise ConfigError('contains requires strings')
            else: typed(pred['value'],spec)

    def discover(self, entrypoint):
        return {'registry_revision': self.revision, 'presets': copy.deepcopy(list(self.presets.values())), 'quarantined': dict(self.quarantined), 'policies': {k:copy.deepcopy(v) for k,v in self.policies.items() if v['entrypoint']==entrypoint}, 'unavailable_policies':dict(self.unavailable_policies), 'unavailable_routes':dict(self.unavailable_routes), 'capability_status':'unverified', 'admissions_enabled': self.admissions_enabled}

    def refresh_yaml(self, text):
        try:
            return Registry.from_yaml(text)
        except ConfigError:
            self.admissions_enabled=False
            raise
