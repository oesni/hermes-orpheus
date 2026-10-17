# Local Hermes reviewer-preset integration

Executed 2026-10-17 against the user's actual local Hermes revision `d923a5eb487a17c0a68801bba9ef0f56c81040a8`, default profile, with real inference. Hermes core checkout remained clean. Orpheus was installed using the public directory-plugin loader; `hermes plugins doctor hermes-orpheus --ci` passed discovery, manifest parsing, import and all four tool registrations. The managed runtime resolves declared plugin Python dependencies through `hermes plugins enable`.

## Configuration and execution

A persistent `reviewer` preset fixes the locally configured `claude-subscription-directsdk-experimental` / `claude-opus-5-5[1m]` pair, carries read-only review instructions, and omits effort. Host fallback lists were empty; the exact configured tuple was authorized for this smoke test. Configuration is under `~/.hermes/orpheus/`; the original Hermes config was backed up privately before adding plugin settings. Only the CLI toolset keeps the added Orpheus tools; other platform toolsets retain their previous values. No gateway restart was performed.

A new real parent session used the existing model through `hermes chat --query-file … --format stream-json --toolsets orpheus --max-turns 20 --run-budget 240 --ignore-rules --in <private-test-directory>`. The test-only rules bypass isolates the synthetic fixture from personal memory/project instructions; this is not a memory/skill-inheritance test. No project code, memory, skills or credentials were supplied as review content.

The parent discovered `reviewer`, called Orpheus spawn exactly once, and polled the same request through RUNNING to SUCCEEDED. The child returned the expected concrete defect: an input of 10,000 cents yields 10,000 instead of 9,000 because the discount predicate uses `>` rather than `>=`. The parent returned the child result.

## Evidence and limits

[receipt.json](receipt.json) contains sanitized verifier output plus separately labeled `operator_metadata` from the installation checks. The verifier establishes the linked calls/result only; `operator_metadata.redacted_export_sha256` hashes the private redacted public session export, not the raw stream. The raw stream and redacted public session export remain outside Git. `tests/live/verify_review_export.py` checks actual assistant/tool-response links, request identity, SUCCEEDED + ready, and the child finding; final assistant prose alone cannot pass. Hermes exports deferred calls through the public `tool_call` wrapper: the verifier accepts a singleton underlying call while retaining outer call-ID linkage and rejects ambiguous batches or alternative delegation.

This proves actual plugin loading, preset discovery, real native subagent execution and result retrieval on this host/provider. The accepted model/provider pair is recorded; independent per-request effective settings remain unobserved (`observed: null`). Webhooks, Jev, other providers, cancellation, restart recovery and memory/skill updates were not tested live. No claim of tool-level permission isolation is made: the child was instructed to review without tools, and stock empty toolsets do not mean no tools.
