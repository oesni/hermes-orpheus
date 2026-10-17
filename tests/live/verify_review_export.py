"""Verify canonical `hermes sessions export --format jsonl` evidence offline.

Only linked assistant tool calls and actual tool-role responses count. Final
assistant claims are never accepted as lifecycle or child-result evidence.
"""
import argparse
import json
from pathlib import Path


def object_value(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError('expected_object')
    return value


def verify(session):
    session = object_value(session)
    messages = session.get('messages', [])
    if not isinstance(messages, list):
        raise ValueError('invalid_messages')
    calls = {}
    discover_index = None
    spawn = None
    completion = None
    spawn_calls = 0
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError('invalid_message')
        if message.get('role') == 'assistant':
            tool_calls = message.get('tool_calls') or []
            if isinstance(tool_calls, str):
                tool_calls = json.loads(tool_calls)
            if not isinstance(tool_calls, list):
                raise ValueError('invalid_tool_calls')
            for call in tool_calls:
                if not isinstance(call, dict):
                    raise ValueError('invalid_tool_call')
                function = object_value(call.get('function') or {})
                name = function.get('name')
                arguments = object_value(function.get('arguments', {}))
                if name == 'tool_call':
                    # Hermes deferred local tools keep the outer call ID and
                    # return the underlying tool's result without an envelope.
                    # Match tools.tool_search.resolve_underlying_call: local
                    # calls must be singletons, never infer batch associations.
                    nested = arguments.get('calls')
                    if not isinstance(nested, list) or len(nested) != 1 or not isinstance(nested[0], dict):
                        raise ValueError('unsupported_tool_call_bridge_shape')
                    name = nested[0].get('name')
                    arguments = object_value(nested[0].get('arguments', {}))
                if not isinstance(name, str):
                    raise ValueError('invalid_tool_name')
                if name and ('delegate' in name or 'subagent' in name or name == 'spawn_agent') and name != 'orpheus_spawn':
                    raise ValueError('alternative_delegation_observed')
                if name == 'orpheus_spawn':
                    spawn_calls += 1
                    if spawn_calls > 1:
                        raise ValueError('multiple_spawn_calls')
                if name not in ('orpheus_presets','orpheus_spawn','orpheus_status'):
                    continue
                call_id = call.get('id')
                if not isinstance(call_id, str) or not call_id or call_id in calls:
                    raise ValueError('invalid_tool_call_identity')
                calls[call_id] = (index, name, arguments)
        elif message.get('role') == 'tool':
            tool_call_id = message.get('tool_call_id')
            if not isinstance(tool_call_id, str):
                raise ValueError('invalid_tool_result_identity')
            linked = calls.get(tool_call_id)
            if not linked:
                continue
            call_index, name, args = linked
            result = object_value(message.get('content'))
            if name == 'orpheus_presets':
                presets = result.get('presets', [])
                if not isinstance(presets, list) or any(not isinstance(p, dict) for p in presets):
                    raise ValueError('invalid_presets')
                reviewers = [p for p in presets if p.get('id') == 'reviewer']
                if len(reviewers) != 1 or reviewers[0].get('execution_capability') != 'compatible' or reviewers[0].get('capability_reasons') != []:
                    raise ValueError('reviewer_not_compatible')
                discover_index = index
            elif name == 'orpheus_spawn':
                if spawn is not None:
                    raise ValueError('multiple_spawns')
                if discover_index is None or discover_index >= call_index:
                    raise ValueError('missing_prior_discovery')
                if args.get('preset_id') != 'reviewer' or 'discounted_total' not in args.get('task', ''):
                    raise ValueError('wrong_review_task')
                if result.get('state') != 'running' or not isinstance(result.get('request_id'), str) or not result['request_id']:
                    raise ValueError('spawn_not_accepted')
                spawn = result
            elif name == 'orpheus_status' and spawn:
                if args.get('request_id') != spawn['request_id'] or result.get('request_id') != spawn['request_id']:
                    raise ValueError('request_identity_mismatch')
                child = object_value(result.get('result') or {})
                if result.get('state') == 'SUCCEEDED' and child.get('ready') is True:
                    finding = object_value(child.get('summary'))
                    expected = {'function':'discounted_total', 'input_cents':10000, 'actual_cents':10000, 'expected_cents':9000}
                    if any(finding.get(key) != value or type(finding.get(key)) is not type(value) for key,value in expected.items()):
                        raise ValueError('child_finding_incorrect')
                    if not isinstance(finding.get('explanation'), str) or not finding['explanation'].strip():
                        raise ValueError('child_explanation_missing')
                    completion = finding
    if not spawn or not completion:
        raise ValueError('missing_linked_child_completion')
    return {'verified':True,'session_id':session.get('id'),'request_id':spawn['request_id'],
            'launch_accepted':spawn.get('launch_accepted'),'observed':spawn.get('observed'),
            'child_finding':completion,'evidence_kind':'public_session_export_linked_tool_calls',
            'limits':'Transcript proves lifecycle tool execution and returned child result, not effective provider request settings.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export')
    parser.add_argument('--session-id',required=True)
    args=parser.parse_args()
    try:
        rows=[object_value(json.loads(line)) for line in Path(args.export).read_text().splitlines() if line.strip()]
        sessions=[row for row in rows if row.get('id')==args.session_id]
        if len(sessions)!=1:
            raise ValueError('session_identity_not_unique')
        print(json.dumps(verify(sessions[0]),ensure_ascii=False,indent=2))
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(json.dumps({'verified':False,'error':str(exc)}))
        raise SystemExit(1)


if __name__=='__main__':
    main()
