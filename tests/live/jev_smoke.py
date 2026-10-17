"""Explicit opt-in real OpenRouter System One resolver probe; never prints secrets."""
import argparse
import aiohttp
import asyncio
import json
import os
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from orpheus.config import Registry
from orpheus.jev import JevClient
from orpheus.resolver import Resolver, SelectionError

ENDPOINT = 'https://openrouter.ai/api/v1/systemone'
MODEL = 'typesafe/jev-1.14'
KEY = 'OPENROUTER_API_KEY'
CASES = [
    ('simple-review', 'Review this trivial one-line arithmetic function for a single off-by-one bug.', 'reviewer', 'quick'),
    ('complex-review', 'Perform a complex code review of cross-service concurrency, transaction rollback, and race conditions across multiple modules.', 'reviewer', 'deep'),
    ('simple-docs', 'Write a short documentation paragraph explaining a simple hello-world function. No code review is needed.', 'writer', 'quick'),
    ('complex-docs', 'Write comprehensive architecture documentation for a complex distributed transaction system with subtle failure recovery and consensus interactions. This is documentation writing, not code review.', 'writer', 'deep'),
]


def config():
    presets = []
    for name, purpose in [('reviewer', 'Review source code for correctness defects and bugs. Do not write documentation.'), ('writer', 'Write documentation, tutorials and architecture explanations. Do not perform code review.')]:
        presets.append({'id': name, 'purpose': purpose,
            'guidance': 'Simple short tasks use small model with low effort (quick). Complex tasks requiring deep reasoning use large model with high effort (deep).',
            'fields': {'model': {'mode': 'enum', 'candidates': ['small', 'large']}, 'effort': {'mode': 'enum', 'candidates': ['low', 'high']}},
            'compatible_settings': {'quick': {'model': 'small', 'effort': 'low'}, 'deep': {'model': 'large', 'effort': 'high'}}})
    def node(name):
        return {'id': name, 'kind': 'jev', 'model': MODEL, 'projection_fields': ['task.text'], 'required_fields': ['task.text'], 'timeout': 20, 'retries': 0}
    return {'schema_version': 1, 'inventory': {'models': {'small': {'provider': 'synthetic', 'model': 'small-fast-model', 'efforts': ['low']}, 'large': {'provider': 'synthetic', 'model': 'large-reasoning-model', 'efforts': ['high']}}},
        'presets': presets, 'subagent_policy': 'jev-smoke', 'policies': {'jev-smoke': {'entrypoint': 'subagent', 'input_schema': {'task.text': {'type': 'string', 'max_length': 2000, 'required': True, 'trust': 'payload'}}, 'preset_selector': node('preset-choice'), 'field_resolver': node('settings-choice')}}}


def credential(path, key_name=KEY):
    """Read only one literal dotenv value; never execute shell or interpolate it."""
    values = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, sep, value = line.partition('=')
        if sep and key.strip() == key_name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
            values.append(value)
    if len(values) != 1 or not values[0] or any(c.isspace() for c in values[0]):
        raise ValueError('Expected exactly one nonempty literal credential')
    return values[0]


class RecordingResponse:
    def __init__(self, response, entry):
        self.status = response.status
        self.response = response
        self.entry = entry
        self.content = self

    async def read(self, limit):
        raw = await self.response.content.read(limit)
        try:
            data = json.loads(raw)
            model = data.get('model') if isinstance(data, dict) else None
            # Only emit a constrained identifier, never arbitrary response text.
            if isinstance(model, str) and re.fullmatch(r'[A-Za-z0-9_./:-]{1,128}', model):
                self.entry['response_model'] = model
        except (ValueError, UnicodeDecodeError):
            pass
        return raw


class RecordingSession:
    def __init__(self, session, entry):
        self.session = session
        self.entry = entry

    def post(self, *args, **kwargs):
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def request():
            async with self.session.post(*args, **kwargs) as response:
                self.entry['http_status'] = response.status
                yield RecordingResponse(response, self.entry)
        return request()


class RecordingClient(JevClient):
    def __init__(self, token):
        super().__init__(token, endpoint=ENDPOINT)
        self.calls = []

    async def choose(self, **kwargs):
        entry = {'requested_model': kwargs['model'], 'candidate_ids': sorted(kwargs['choices']), 'projection_fields': sorted(kwargs['state'])}
        self.calls.append(entry)
        try:
            async with aiohttp.ClientSession() as session:
                self.session = RecordingSession(session, entry)
                answer = await super().choose(**kwargs)
        except SelectionError as exc:
            entry['error_code'] = exc.code
            raise
        entry.update(answer)
        return answer


async def run(token):
    client = RecordingClient(token)
    resolver = Resolver(Registry.from_dict(config()), client)
    results = []
    for case_id, task, preset, settings in CASES:
        start = len(client.calls)
        row = {'case_id': case_id, 'expected': {'preset_id': preset, 'tuple_id': settings}}
        try:
            result = await resolver.resolve('subagent', task)
            row['selected'] = {key: result[key] for key in ('preset_id', 'tuple_id', 'model', 'effort')}
            row['passed'] = result['preset_id'] == preset and result['tuple_id'] == settings
        except SelectionError as exc:
            row.update(passed=False, error_code=exc.code)
        row['calls'] = client.calls[start:]
        results.append(row)
        if row.get('error_code') in ('authentication_failed', 'invalid_response'):
            break
    return {'endpoint': ENDPOINT, 'requested_model': MODEL, 'scope': 'Real System One API plus production Resolver; synthetic task model inventory; no child execution or native effort application.', 'observed_provider_model': sorted({call['response_model'] for call in client.calls if 'response_model' in call}) or None, 'cases': results, 'passed': len(results) == len(CASES) and all(row['passed'] for row in results)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--token-env', default=KEY, help='Credential variable name in the dotenv file')
    args = parser.parse_args()
    try:
        report = asyncio.run(run(credential(args.env_file, args.token_env)))
    except Exception:
        # Never echo exception objects from credential/network code.
        print(json.dumps({'passed': False, 'error_code': 'probe_setup_or_transport_error'}))
        return 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        os.chmod(output, 0o600)
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
