# Real Jev decision smoke test

On 2026-10-17, the production `Resolver` and `JevClient` called OpenRouter's
`https://openrouter.ai/api/v1/systemone` endpoint with `typesafe/jev-1.14`.
The response model identifier was `typesafe/jev-1.14-20261014` for all eight calls.

Four synthetic task descriptions with explicit domain/complexity cues covered
simple/complex code review and simple/complex documentation. They did not specify a preset ID, model, or effort.
Each resolution made two real decisions: preset selection, then compatible
model/effort tuple selection. All four matched expectations: reviewer/writer and
quick (small/low) versus deep (large/high). All responses were HTTP 200; reported
confidence ranged from 0.94 to 1. This is a bounded smoke test, not a general
routing-quality benchmark.

`receipt.json` is the byte-for-byte original sanitized machine-generated outcome.
`operator-metadata.json` separately records its SHA-256, synthetic task descriptions,
probe hashes and provenance qualifications. `registry.json` is the complete
synthetic configuration. Inventory task
models are placeholders: no task-model execution, Hermes session spawn, webhook
HTTP handling, or native subagent effort application is claimed. Stock Hermes
still cannot apply an explicit subagent effort through this adapter.

The credential was read as a literal from the operator's local `.env`, never
sourced as shell code. Only the named variable was used and only the official
OpenRouter endpoint received it. No credential, raw environment, authorization
header, or raw API response is included in these artifacts. A prior restricted
network attempt failed with `service_unavailable`; the authorized network run
produced this receipt. An earlier explicit-choice protocol smoke test also
passed, but the published receipt is the subsequent task-description run.

To rerun explicitly (incurs API usage), from the repository root:

```sh
.venv/bin/python tests/live/jev_smoke.py \
  --env-file /absolute/private/path/.env \
  --output /private/tmp/orpheus-jev-new-receipt.json
```

The probe defaults to `OPENROUTER_API_KEY`. If your dotenv uses another name,
add `--token-env YOUR_ENV_NAME`. It pins the endpoint and model above, refuses
to overwrite an existing receipt, and emits
only allowlisted decision metadata. Ordinary pytest does not contact the API.

After the recorded live run, the probe gained a generic credential-variable
default and `--token-env` override. The original tested probe hash is preserved in the operator sidecar;
`final_probe_sha256` identifies the version after this credential-argument-only
change. The operator states that the decision cases and API protocol were unchanged;
no API rerun was performed for this CLI plumbing change.

No execution-time production-module hash manifest was captured, so the exact
module bytes loaded by the past run are not cryptographically established. The
receipt hash identifies the published sanitized receipt, which the operator verified
against the retained original probe output; it is not a hash or archive of the raw
provider response.
