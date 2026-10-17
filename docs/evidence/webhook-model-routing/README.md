# Webhook model routing evidence

Pinned upstream: `NousResearch/hermes-agent@7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357`.

Run `python3 docs/evidence/webhook-model-routing/probe.py` from the Orpheus purpose worktree. The first source snapshot defaults to `/private/tmp/orpheus-webhook-verify` (override with argv[1]); the API snapshot is `/tmp/orpheus-extension-check`. Populate those directories with the upstream paths listed in `source-sha256.json` from this exact commit. Snapshot source is not vendored. Hashes identify the files inspected; the script regenerates the manifest and should be compared to this recorded version when reproducing.

`results.txt` records six passing output groups. This is **extracted upstream source execution with stubs plus AST checks**, not an installed plugin or live gateway integration test. Registry delivery, provider resolution and transport are stubbed. No API credentials, paid model calls, real webhook deliveries or Jev calls were used.

## Findings

- Native `pre_gateway_dispatch` consumes `skip`, `rewrite` (text), or `allow`; returned model/provider fields have no effect. Its exposed live gateway object does not turn private gateway mutation into a stable public API.
- Native `post_gateway_admission` only consumes `handled`/`reply`, with snapshot inputs; errors fail open. Source inspection only for this hook.
- LLM request middleware can rewrite the request model. Actual extracted dispatch forwards that request through the original agent callback. Agent model/provider/base URL identity remains unchanged. This is insufficient evidence for coherent cross-provider session construction or first-turn preset application.
- The native API `/v1/runs` accepts explicit model/provider/model_options. Actual decoding and runtime selection resolve the chosen pair for a **fresh, unaliased session without existing model override**; provider-resolution invocation is tested with a stub. Reasoning effort decoding is executed. Endpoint-to-launch and constructor keyword forwarding is inspected via AST.
- A plugin-owned webhook endpoint mounted through the documented API-server platform handler can validate an event, select a preset via rules/Jev, then invoke the authenticated `/v1/runs` HTTP contract. This is a plugin-only architectural route, not an extension of the existing native webhook dispatch path. Custom ingress authentication, filtering, deduplication, receipt reactions, delivery, persistence/restart and concurrency behavior still need implementation and integrated tests.

API precedence requires attention: session overrides/persisted model and model-route aliases can supersede a direct request. Invalid effort values are silently ignored by the helper, so Orpheus must validate selected values before submission. The API agent retains the configured fallback chain; a chosen initial model does not promise that all calls will use it.
