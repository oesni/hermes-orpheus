"""Hermes entry point using PluginContext's public registration APIs."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import yaml
from .config import Registry, UniqueLoader
from .host import SubagentAdapter, HostError
from .deployment import validate_routes
from .jev import JevClient
from .resolver import Resolver


EMPTY_CONFIG = {'schema_version': 1, 'inventory': {'models': {}}, 'presets': [], 'policies': {}}


def register(ctx):
    """Register tools and optional API ingress; never launch work on import/load."""
    def setting(name, default=None):
        getter = getattr(ctx, 'get_config', None)
        return getter(name, default) if callable(getter) else default

    config_path = setting('config_path', os.environ.get('ORPHEUS_CONFIG'))
    deployment_path = setting('deployment_path', os.environ.get('ORPHEUS_DEPLOYMENT'))
    state_dir = setting('state_dir', os.environ.get('ORPHEUS_STATE_DIR'))
    if state_dir is None:
        state_dir = str(Path(os.environ.get('HERMES_HOME', str(Path.home() / '.hermes'))) / 'orpheus')
    registry = Registry.from_yaml(Path(config_path).read_text()) if config_path else Registry.from_dict(EMPTY_CONFIG)
    deployment = yaml.load(Path(deployment_path).read_text(), Loader=UniqueLoader) if deployment_path else {}
    validate_routes(registry, deployment)
    resolver = Resolver(registry, JevClient(os.environ.get(deployment.get('jev_token_env', 'TYPESAFE_API_KEY'))))
    adapter = SubagentAdapter(ctx.subagent_lifecycle, state_dir, deployment.get('subagent', {}), redact_literals=deployment.get('redact_literals', []))
    if callable(getattr(ctx, 'on_unload', None)):
        ctx.on_unload(adapter.close)

    async def presets(args, **kwargs):
        if args:
            raise HostError('invalid_input', 'Discovery takes no parameters.')
        data = registry.discover('subagent')
        data['host_capabilities'] = adapter.capabilities()
        for preset in data['presets']:
            reasons = []
            for candidate in preset['compatible_settings'].values():
                fields = {k: v['value'] for k, v in preset['fields'].items() if v['mode'] == 'fixed'}
                fields.update(candidate)
                inventory = registry.inventory[fields.pop('model')]
                fields.update({'model': inventory['model'], 'provider': inventory['provider']})
                try:
                    adapter.preflight({'resolved': fields})
                except HostError as exc:
                    reasons.append(exc.code)
            preset['execution_capability'] = 'unverified' if reasons else 'compatible'
            preset['capability_reasons'] = sorted(set(reasons))
        if not data['presets']:
            data['guidance'] = 'Configure at least one compatible preset before spawning.'
        return data

    async def spawn(args, **kwargs):
        if not isinstance(args, dict) or set(args) - {'task', 'context', 'preset_id', 'proposals'}:
            raise HostError('invalid_input', 'Unknown spawn parameters.')
        selection = await resolver.resolve('subagent', args.get('task'), context=args.get('context'),
                                           preset_id=args.get('preset_id'), proposals=args.get('proposals'))
        # Deliver pending task cancellation before crossing the irreversible launch boundary.
        await asyncio.sleep(0)
        return adapter.launch(selection, args['task'], args.get('context'))

    async def status(args, **kwargs):
        validate_id(args)
        return adapter.status(args['request_id'])

    async def cancel(args, **kwargs):
        validate_id(args)
        return adapter.cancel(args['request_id'])

    for name, description, handler, properties, required in [
        ('orpheus_presets', 'Discover presets, allowed tuples and capability limits.', presets, {}, []),
        ('orpheus_spawn', 'Spawn a native child using the bound selection policy.', spawn,
         {'task': {'type': 'string'}, 'context': {'type': 'object'}, 'preset_id': {'type': 'string'}, 'proposals': {'type': 'object'}}, ['task']),
        ('orpheus_status', 'Read an owned child status and result.', status, {'request_id': {'type': 'string'}}, ['request_id']),
        ('orpheus_cancel', 'Request cancellation of an owned child.', cancel, {'request_id': {'type': 'string'}}, ['request_id']),
    ]:
        ctx.register_tool(name=name, toolset='orpheus', description=description, is_async=True,
                          schema={'name': name, 'description': description, 'parameters': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}},
                          handler=tool_envelope(handler))
    if registry.webhooks:
        from .webhook import create_platform_handler
        ctx.register_platform_handler('api_server', create_platform_handler(registry, resolver, deployment, state_dir))


def validate_id(args):
    if not isinstance(args, dict) or set(args) != {'request_id'} or not isinstance(args['request_id'], str):
        raise HostError('invalid_input', 'A request_id is required.')


def tool_envelope(handler):
    async def invoke(args, **kwargs):
        try:
            return json.dumps(await handler(args, **kwargs), ensure_ascii=False)
        except Exception as exc:
            # Provider exception strings can contain secrets; expose a class only.
            return json.dumps({'error': {'code': getattr(exc, 'code', 'internal_error')}})
    return invoke
