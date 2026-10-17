# Claude implementation review — round 3

Requested model `claude-opus-5-5`; reported models ['claude-opus-5-5']; CLI exit 0. Full supplied source snapshot, no tools.

# hermes-orpheus implementation review, round 3

I reviewed only the text you supplied and ran nothing. The hash-pinned vendor fixtures are out of scope. An approval here covers the source only. It does not certify production deployment, provider behaviour or the real Hermes host.

**Verdict: APPROVE.** Round 2's P2 is fixed and its two P3 items are mostly fixed. I found no P1 or P2 issues in the current snapshot. The three P3 items below should still be fixed, ideally before deployment acceptance.

## Round-2 findings

- **P2-1 (a run the host no longer knows about stays `running` forever): fixed.**
  - `RunClient._call` now raises `HostRunUnavailable` when status (GET `/v1/runs/{id}`) or stop returns 404.
  - `observe` then moves the row to `unknown` with `host_run_unavailable` and `result_availability: 'unavailable'`. `Ledger.change` gives the row a retention deadline.
  - `abandon` now works on the row because it is `unknown`.
  - A failed launch POST is still classified separately: `LaunchRejected` versus `ambiguous_acceptance`.
  - `test_restart_missing_host_run_and_stop_become_unknown` reopens the ledger and covers both the status path and the stop path.
- **P3-1 (configured but unusable webhook wiring): fixed.**
  - `validate_routes` checks that each route's auth profile and target exist and that effective scopes are unique. It is used by the CLI, `register` and `WebhookService.__init__`.
  - `task_fields` must now be nonempty.
  - An empty extracted task is rejected with `empty_task` before `reserve`, so no replay tombstone is written.
  - Tests cover each case.
- **P3-2 (unbounded `unknown` and abandoned rows): mostly fixed.**
  - Abandoned rows get a retention deadline, are excluded from `active()`, and are compacted. Compaction keeps the dispatch receipt fields, so a late acceptance is still recorded but does not bring the row back to life.
  - `unknown` rows get a retention deadline when they enter that state.
  - `owners` is pruned to active IDs on every reconcile pass.
  - One part is still open; see P3-1 below.

## P3

**1. `unknown` rows that still have a host ID are polled forever (`ledger.py` `Ledger.active`, `webhook.py` `reconcile`/`observe`).**

- **Trigger:**
  1. Restart Hermes with N runs that the host has forgotten.
  2. Each row becomes `unknown/host_run_unavailable`, but `active()` still returns it, so `reconcile` reclaims it and calls `observe` every 10 seconds.
  3. `observe` sends GET `/v1/runs/{id}` again, plus POST `/stop` first if `cancel_requested` is set. Each call returns 404 and the row is rewritten as `unknown`.
- **Result:** this continues until an operator abandons each row. Compaction bounds the stored data but not the polling. Background traffic grows with every restart, at one or two HTTP calls per row every 10 seconds, with no end.
  - `target_identity_changed` rows behave the same way, though they generate no host traffic.
- **Fix:**
  - After classifying a row as `host_run_unavailable` or `target_identity_changed`, stop polling it automatically. For example, exclude it from `active()` by error code, or use capped exponential backoff with a final stop.
  - Keep operator `reconcile` (`_explicit`) able to observe it.
  - Keep transient 5xx and timeout errors on the normal retry path.
  - Add a test that a second reconcile pass makes no further host calls.

**2. One invalid preset used by a webhook policy makes the whole registry fail to load (`config.py` `Registry.__init__`, route binding check).**

- **Trigger:**
  1. Edit one preset so that it is quarantined, for example by emptying its candidates.
  2. `_policy` then adds that webhook policy to `unavailable_policies` ("Unavailable preset reference").
  3. The route loop then raises `ConfigError('Webhook route policy unavailable or wrong entrypoint')`.
  4. As a result:
     - `register` raises, so none of the four native tools are registered, including those for presets that are still valid.
     - `orpheus validate` returns only an error code instead of naming the quarantined preset.
     - `refresh_yaml` freezes admissions for everything.
- **Why it matters:**
  - This conflicts with requirement 4: one invalid preset must not make unrelated valid presets unavailable.
  - It is also inconsistent with the subagent binding, where an unavailable policy degrades without raising.
  - Ingress already returns 503 `route_unavailable` for a route whose policy is unavailable.
- **Fix:**
  - Keep `ConfigError` for structural binding errors only: an unknown policy name, or a policy with the wrong entry point.
  - For a policy that is known but unavailable, mark only that route unavailable.
  - Report unavailable routes in `discover` and `validate` (nonzero exit) so they are not silently accepted.
  - Update `test_route_policy_binding_rejected('unavailable')` to match.

**3. The CLI reports deployment wiring errors under a misleading code (`cli.py` `main`).**

- **Trigger:** run `orpheus validate --deployment` when a route's auth profile is missing. `validate_routes` raises a plain `ValueError('missing_route_auth_profile')`, which has no `.code`, so the CLI prints `{"valid": false, "error": "source_unavailable"}`.
- **Result:** an operator is pointed at file access instead of the missing reference. The exit status is correct; the diagnostic is wrong.
- **Fix:** give the deployment errors a `code`, or use `str(exc)` as the code when the exception is a deployment validation error. Assert the printed code in `CrossFileCliTests`.

## Checked and not reported

- **Authentication and replay:**
  - HMAC-SHA256 is computed over the raw body bytes and compared in constant time as bytes; the non-ASCII header crash is fixed.
  - Route, secret, registry admission status and target are checked before the body is read.
  - Content type and body size are checked after authentication.
  - The replay tombstone is the full body digest within a unique stable scope, and it survives restarts.
  - Filters run on routing fields before reservation.
  - Payload values cannot choose the preset, model or effort.
- **Durable launch and ownership:**
  - Each step that commits to a launch is a fenced compare-and-swap on generation and lease.
  - A crash between `starting` and submit leaves a row with no host ID. It becomes `unknown` only through a recovered (expired-lease) claim, and it is never resubmitted.
  - `publish_acceptance` is gated by dispatch token, idempotency key and payload digest, and it writes an immutable receipt. A late acceptance after a recovered owner marked the row `unknown`, or after it was abandoned, is recorded without being resubmitted or brought back to life.
  - An `Idempotency-Key` is sent with each submit.
- **Cancellation:**
  - Cancelling during resolve or selection bumps the generation, so a late selection result cannot be submitted.
  - Cancelling during submit keeps the row in `starting` with `cancel_requested`. After acceptance, the next owned observe sends stop.
  - A cancel on a terminal row does nothing.
- **Restart resolution:** `resolving` rows are resolved against the durable registry snapshot. A target change before launch fails closed, as documented.
- **Rules and Jev:**
  - Rules: unique priorities, deterministic first match, and explicit no-match handling. At runtime, rules see only routing fields, and predicates are validated against the routing fields shared by every route that uses the policy.
  - Jev: finite choices (at most 255), a bounded response size, and validated probabilities and confidence.
  - Retries happen only for transient error codes, within a 45-second overall deadline.
  - Fallback follows only configured edges, and webhooks never use the parent LLM.
  - Jev receives only fields projected from the route's routing and task fields.
- **Native adapter:**
  - Preflight requires the exact verified provider/model/effort tuple.
  - Explicit effort requires the per-launch-v1 marker.
  - Fallback requires either the control marker or an operator assertion that fallback is disabled.
  - An empty toolset is rejected, and toolsets are limited to the operator's allowed set.
  - Launch intent is stored before invocation, and any exception becomes `unknown` without a retry.
  - Native handles are stripped from results, redaction applies globally, and retention erases stored inputs.
- **Packaging:** the entry point and wheel are correct.
- **Compatibility patch:** effort and fallback are validated both when the request is checked and when the child is built. The parent and sibling runtimes are not mutated.

## Remaining deployment gates (already disclosed, not counted as defects)

- Whether the live `/v1/runs` honours `provider`, `model_options` and `instructions`, and whether inherited safety instructions are kept.
- Whether the provider applies effort and actually disables fallback.
- Whether the host's native `status`/`cancel` enforces caller ownership.
- The real child-runtime ordering, which the patch tests stub out.
- Whether `register_platform_handler` mounts the routes before the aiohttp app freezes. If it does not, the reconciler and cleanup handlers never attach.
- Whether the API server's own authentication middleware lets unauthenticated webhook ingress through.

The fake host, provider and stubbed upstream tests do not establish any of these.
