"""Offline validation/inspection; no provider calls or Hermes installation needed."""
import argparse
import json
from pathlib import Path
import yaml
from .config import Registry, UniqueLoader
from .deployment import validate_routes


def main(argv=None):
    parser = argparse.ArgumentParser(prog='orpheus')
    parser.add_argument('command', choices=['validate', 'inspect'])
    parser.add_argument('config')
    parser.add_argument('--deployment', help='Validate an optional operator deployment YAML too')
    parser.add_argument('--entrypoint', choices=['subagent','webhook'], default='subagent')
    args = parser.parse_args(argv)
    try:
        registry = Registry.from_yaml(Path(args.config).read_text())
        if args.deployment:
            validate_routes(registry, yaml.load(Path(args.deployment).read_text(), Loader=UniqueLoader))
        report = registry.discover(args.entrypoint)
        if args.command == 'inspect':
            for preset in report['presets']:
                expanded = []
                for tuple_id, values in preset['compatible_settings'].items():
                    settings = {name: field['value'] for name, field in preset['fields'].items() if field['mode'] == 'fixed'}
                    settings.update(values)
                    model_ref = settings.pop('model')
                    model = registry.inventory[model_ref]
                    settings.update(model=model['model'], provider=model['provider'])
                    expanded.append({'tuple_id': tuple_id, 'model_ref': model_ref, 'resolved': settings})
                preset['expanded_settings'] = expanded
                preset['candidate_count'] = len(expanded)
        invalid = bool(registry.quarantined or registry.unavailable_policies or report.get('unavailable_routes'))
        if args.command == 'validate':
            report = {k: report.get(k, {}) for k in ('registry_revision','quarantined','unavailable_policies','unavailable_routes','capability_status')}
            report['valid'] = not invalid
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if invalid else 0
    except (ValueError, OSError, yaml.YAMLError) as exc:
        print(json.dumps({'valid': False, 'error': getattr(exc,'code','source_unavailable')}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
