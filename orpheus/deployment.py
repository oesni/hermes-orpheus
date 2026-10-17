"""Strict operator deployment settings and private state-file preparation."""
import os
import stat
from pathlib import Path


class DeploymentError(ValueError):
    """Stable, nonsecret operator-facing configuration diagnostic."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _mapping(value, allowed):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise DeploymentError('invalid_deployment_keys')


def _strings(value):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise DeploymentError('invalid_deployment_string_list')


def validate_subagent(value):
    _mapping(value, {'fallback_disabled', 'verified_settings', 'allowed_toolsets'})
    if 'fallback_disabled' in value and type(value['fallback_disabled']) is not bool:
        raise DeploymentError('invalid_fallback_setting')
    _strings(value.get('allowed_toolsets', []))
    settings = value.get('verified_settings', [])
    if not isinstance(settings, list):
        raise DeploymentError('invalid_verified_settings')
    for entry in settings:
        _mapping(entry, {'provider', 'model', 'effort'})
        if not {'provider', 'model'} <= set(entry) or any(not isinstance(item, str) or not item for item in entry.values()):
            raise DeploymentError('invalid_verified_settings')


def validate_deployment(value):
    _mapping(value, {'subagent', 'auth_profiles', 'targets', 'operators', 'redact_literals', 'jev_token_env'})
    validate_subagent(value.get('subagent', {}))
    _strings(value.get('redact_literals', []))
    if 'jev_token_env' in value and (not isinstance(value['jev_token_env'], str) or not value['jev_token_env']):
        raise DeploymentError('invalid_jev_token_env')
    for key in ('auth_profiles', 'targets', 'operators'):
        if not isinstance(value.get(key, {}), dict):
            raise DeploymentError('invalid_deployment_mapping')
        if any(not isinstance(name, str) or not name for name in value.get(key, {})):
            raise DeploymentError('invalid_deployment_name')
    for scopes in value.get('operators', {}).values():
        _strings(scopes)
    for auth in value.get('auth_profiles', {}).values():
        _mapping(auth, {'scope', 'principal', 'secret_env', 'signature_header'})
        if not {'scope', 'secret_env'} <= set(auth) or any(not isinstance(item, str) or not item for item in auth.values()):
            raise DeploymentError('invalid_auth_profile')
    for target in value.get('targets', {}).values():
        _mapping(target, {'url', 'token_env', 'principal', 'verified', 'fallback_disabled', 'models', 'allow_loopback_http'})
        for key in ('verified', 'fallback_disabled', 'allow_loopback_http'):
            if key in target and type(target[key]) is not bool:
                raise DeploymentError('invalid_target_flag')
        for key in ('url', 'token_env', 'principal'):
            if key in target and (not isinstance(target[key], str) or not target[key]):
                raise DeploymentError('invalid_target_identity')
        models = target.get('models', {})
        if not isinstance(models, dict):
            raise DeploymentError('invalid_target_models')
        for name, model in models.items():
            if not isinstance(name, str) or not name:
                raise DeploymentError('invalid_target_models')
            _mapping(model, {'provider', 'efforts'})
            if not isinstance(model.get('provider'), str) or not model['provider']:
                raise DeploymentError('invalid_target_models')
            _strings(model.get('efforts', []))
    return value


def validate_routes(registry, deployment):
    """Resolve administrator references without requiring live secrets or targets."""
    validate_deployment(deployment)
    source = getattr(registry, 'source', registry)
    if not isinstance(source, dict):
        raise DeploymentError('invalid_registry_source')
    scopes = set()
    for route in source.get('webhooks', []):
        auth_name = route.get('auth_profile')
        target_name = route.get('execution_target')
        if not isinstance(auth_name, str) or auth_name not in deployment.get('auth_profiles', {}):
            raise DeploymentError('missing_route_auth_profile')
        if not isinstance(target_name, str) or target_name not in deployment.get('targets', {}):
            raise DeploymentError('missing_route_execution_target')
        auth = deployment['auth_profiles'][auth_name]
        scope = route.get('security_scope', auth['scope'])
        if not isinstance(scope, str) or not scope or scope in scopes:
            raise DeploymentError('invalid_or_duplicate_route_security_scope')
        scopes.add(scope)
    return deployment


def secure_state_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise DeploymentError('state_directory_symlink')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if info.st_uid != os.getuid():
        raise DeploymentError('state_directory_owner')
    path.chmod(0o700)
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise DeploymentError('state_directory_permissions')
    return path


def secure_sqlite_files(path):
    """Private directory prevents sidecar exposure without global umask races."""
    path = Path(path)
    secure_state_directory(path.parent)
    for suffix in ('', '-wal', '-shm', '-journal'):
        candidate = Path(str(path) + suffix)
        if candidate.is_symlink():
            raise DeploymentError('state_file_symlink')
        if candidate.exists():
            if candidate.stat().st_uid != os.getuid():
                raise DeploymentError('state_file_owner')
            candidate.chmod(0o600)
