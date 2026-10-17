# Claude implementation review — round 4

Requested model `claude-opus-5-5`; reported models ['claude-opus-5-5']; CLI exit 0. Full supplied source snapshot, no tools.

# hermes-orpheus implementation review, round 4

I reviewed only the supplied source snapshot and ran nothing. The hash-pinned vendor fixtures are out of scope. An approval here covers the source only. It does not certify production deployment, provider behaviour or the real Hermes host.

**Verdict: APPROVE.** All three round-3 P3 items are fixed. I found no P1 or P2 issues. One new low-severity P3 is below; fix it when convenient.

## Round-3 findings

- **P3-1 (`unknown` rows polled forever): fixed.**
  - `Ledger.active()` now leaves out `unknown` rows whose error code is `host_run_unavailable` or `target_identity_changed`, so the periodic reconciler drops them.
  - Each reconcile pass also prunes `owners` to the active IDs.
  - An operator can still observe these rows through `reconcile`. It runs `observe` with `_explicit=True` and works whether or not `claim` succeeds, because `change` still accepts the stored generation while the lease is live.
  - An operator `cancel` on such a row still sends stop.
  - Transient 5xx and timeout errors leave the row `running`, so it stays pollable.
  - `test_permanent_observation_failure_waits_for_explicit_reconcile` shows that a second pass makes no host call and that an explicit reconcile does. `test_transient_observation_failure_remains_pollable` covers the transient case.
- **P3-2 (one bad preset made the whole registry fail to load): fixed.**
  - `ConfigError` is now raised only for structural binding errors: an unknown policy name, or a policy with the wrong entry point.
  - A policy that exists but is unavailable now goes into `unavailable_routes` instead of raising.
  - `unavailable_routes` is reported by `discover`, and the CLI `validate` treats it as invalid (nonzero exit).
  - At ingress, such a route still returns 503 `route_unavailable`. That works because a route can only be in `unavailable_routes` when its policy is in `unavailable_policies`.
  - `test_invalid_webhook_preset_isolated_from_valid_native_and_route` shows that valid presets, valid policies and valid routes keep working, and that admissions stay enabled.
- **P3-3 (misleading CLI error code): fixed.**
  - `DeploymentError` now carries a stable `code`, and both `validate_deployment` and `validate_routes` use it.
  - `CrossFileCliTests` asserts that the CLI prints `missing_route_auth_profile`.

## P3

**1. The reconciler keeps renewing rows that nothing can advance automatically (`webhook.py` `reconcile`/`schedule`/`observe`, `ledger.py` `active`).**

There are two cases with the same root cause.

**Case (a): a `starting` row can get stuck for the life of the process.**
1. Inside `process`, `publish_acceptance` raises, for example from a SQLite error after the host has accepted the run. The exception is logged and re-raised.
2. The outer `except Exception` then tries to change the row from `resolving`/`selected` to `failed`. That compare-and-swap fails because the row is `starting`, so the row stays `starting` with no host ID.
3. On every later pass, `reconcile` sees that `owners[rid]` matches the row's generation, so it calls `renew` and then `schedule`. `observe` returns immediately because the row is not `_recovered`.
4. Because the lease is renewed every 10 seconds, it never expires. As a result:
   - the row never becomes `unknown`;
   - `abandon` refuses it, because it is not `unknown`;
   - operator `reconcile` cannot move it either, because `claim` fails and `observe` sees no `_recovered` flag.

The log message says "operator reconciliation required", but no operator action can resolve the row until Hermes restarts. The trigger is rare, because it needs a database failure after earlier commits succeeded.

**Case (b): ambiguous rows with no host ID cost a little work forever.**
- These are rows marked `unknown` with `ambiguous_acceptance`, or with no host ID in the response.
- `active()` keeps returning them, so every 10 seconds each one costs one `renew` write plus a scheduled task. `observe` does nothing for them.
- No host traffic is involved, but the work grows with every ambiguous row until an operator abandons it.
- Leaving these rows out of the automatic pass would be safe. A late acceptance moves the row to `running` through `publish_acceptance`, and `running` rows are in `active()` again.

**Fix:**
- Renew an owned row only while its job is still in `self.jobs`. Otherwise treat the row as recovered, so a `starting` row with no host ID moves to `unknown`.
- Leave `unknown` rows with no `host_id` out of `active()`, as was done for `host_run_unavailable`.
- Add a test that a `publish_acceptance` failure ends in `unknown` and can be abandoned without a restart.

## Checked and not reported

- **Authentication and replay:**
  - HMAC is computed over the raw body bytes and compared in constant time as bytes.
  - The route, secret and target are checked before the body is read.
  - Content type and body size are checked after authentication.
  - The replay tombstone is the body digest within a unique stable scope.
  - Filtered and empty-task bodies are rejected before `reserve`, so they leave no tombstone.
  - Payload values cannot choose the preset, model or effort.
- **Durable launch, ownership and cancellation:**
  - Each step is a fenced compare-and-swap on generation and lease.
  - A run is never resubmitted.
  - Acceptance receipts are immutable and tied to the dispatch token.
  - A cancel during selection bumps the generation, so the late selection result cannot be submitted.
  - A cancel during submit is carried into an owned stop once the run is accepted.
  - A cancel on a terminal row does nothing.
- **Configuration and policies:**
  - Quarantine and route binding are now consistent between the subagent and webhook entry points.
  - Rules see only routing fields, at load time and at runtime.
  - Jev uses finite choices with bounded retries and deadlines, and nothing falls back to an LLM.
- **Native adapter:**
  - Preflight requires the exact verified provider/model/effort tuple.
  - Effort requires the per-launch marker. Fallback requires the control marker or the operator's assertion that fallback is disabled.
  - An empty toolset is rejected.
  - A launch exception is recorded as `unknown` and is not retried.
  - Native handles are stripped from results, and redaction is applied.
- **Packaging and compatibility patch:** unchanged from round 3 and correct.

## Remaining deployment gates (disclosed, not counted as defects)

- Whether the live `/v1/runs` honours `provider`, `model_options` and `instructions`.
- Whether the provider actually applies effort and disables fallback.
- Whether native `status`/`cancel` enforces ownership.
- Whether `register_platform_handler` mounts the routes before the aiohttp app freezes.
- Whether the API server's authentication middleware lets unauthenticated webhook ingress through.

The fake host, provider and stubbed upstream tests do not establish any of these.
