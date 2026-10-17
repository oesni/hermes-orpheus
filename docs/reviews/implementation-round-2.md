# Claude implementation review — round 2

Requested model `claude-opus-5-5`; reported models ['claude-opus-5-5']; CLI exit 0. Full supplied source snapshot, no tools.

# hermes-orpheus implementation review, round 2

I reviewed only the supplied text and ran nothing. The hash-pinned vendor fixtures are excluded. An approval here would cover the source only, not production deployment or provider behaviour.

**Verdict: REQUEST_CHANGES.** All five round-1 items are corrected, but there is one new P2 and two P3 items.

## How the round-1 findings were resolved

- **Round-1 P2-1 (operator reconcile during submit loses the host run): fixed.**
  - `observe` now marks a `starting` row without a `host_id` as `unknown` only when the caller has just won `claim` on an expired lease (`_recovered`).
  - `Ledger.publish_acceptance` no longer depends on lease or generation. It accepts `starting`, `unknown` or `running`, and writes an immutable receipt in the same transaction.
  - A publication failure is logged.
  - `test_reconcile_while_submit_and_late_acceptance_survives_new_owner` covers both the operator path and the recovered-owner path.
- **Round-1 P2-2 (a target edit strands launched runs): fixed.**
  - Observation is now tied only to the target's URL and principal.
  - If either changes, the row becomes `unknown` with error `target_identity_changed`, so an operator can abandon it.
  - Rotating the token or changing `verified` no longer blocks observation (covered by a test).
- **Round-1 P3-1 (reconcile loop dies on errors): fixed.** Errors are now isolated per iteration, per row and per compaction pass, and a test covers this.
- **Round-1 P3-2 (unsupported config accepted): mostly fixed.**
  - Header extraction and `verified_metadata` are now rejected at load.
  - Unknown, wrong-entrypoint or unavailable route policies, and a bad `subagent_policy` binding, now raise `ConfigError`.
  - The deployment file is now strictly validated: unknown keys, operator scopes that must be lists, and typed `verified_settings`.
  - Remaining gaps are in P3-1 below.
- **Round-1 P3-3 (routing fields not enforced): fixed.**
  - Rule predicates are validated against the routing fields shared by every route that uses the policy.
  - Route filters are validated against that route's `routing_fields`.
  - At runtime, the resolver builds `rule_values` from `routing_fields` only.
- **Round-1 P3-4 (`redact_literals` read from two places): fixed.** There is now one top-level `redact_literals`, used by both entry points, and `subagent.redact_literals` is rejected.
- **Round-1 P3-5 (retention and file privacy): mostly fixed.**
  - Finished (terminal) webhook rows are compacted to a replay tombstone, using an indexed scan.
  - Native rows are expired or erased.
  - The state directory is tightened to 0700, and existing database side files to 0600.
  - The non-ASCII signature crash is fixed.
  - Remaining gap: P3-2 below.

## P2

**1. A run the host no longer knows about stays `running` and is polled forever (`webhook.py` `observe` and `RunClient._call`).**

- **Trigger:**
  1. The host stops recognising the `run_id`. Typical causes are a Hermes restart, or the host expiring retained runs.
  2. `GET /v1/runs/{id}` then returns 404, and `_call` raises `RuntimeError('host_unavailable')`.
  3. `observe` swallows every exception (`except Exception: return`).
- **Why the restart case matters:** Orpheus mounts on the same API-server process that serves `/v1/runs`, so restarting Hermes is exactly the restart-recovery scenario.
  - After restart, each `running` row is reclaimed and observed every 10 seconds.
  - It stays `running` with no error.
  - It never gets a `retention_at`, so the task, context, registry snapshot and payload are kept forever.
  - `abandon` only accepts `unknown`, so the operator cannot clear the row.
  - A pending `cancel_requested` fails the same way: a 404 on `/stop` returns before the status call is made.
- **Conflicts with:** requirements 31 and 45 (an unresolvable old run must be shown as unavailable or unknown), and the documented statement that missing host results "remain unavailable/expired".
- **Fix:**
  - Have `_call` raise a typed not-found error for 404 on the status and stop calls.
  - `observe` should then move the row to `unknown`, with an error such as `{'phase':'observation','code':'host_run_unavailable'}` and `result_availability: 'unavailable'`.
  - Keep transient errors (5xx, transport, timeout) as silent retries.
  - Add a test where the fake host returns 404 after a restart.

## P3

**1. Some webhook wiring that is configured but unusable still passes validation.**

- `orpheus validate --deployment` checks the preset file and the deployment file separately. It never checks that each route's `auth_profile` and `execution_target` exist in the deployment, or that the effective security scopes are unique.
- `WebhookService.__init__` catches part of this. A route with an explicit `security_scope` but a missing `auth_profile` still constructs successfully, and every delivery then gets 503 `route_unavailable`. A missing `execution_target` likewise only shows up as runtime 503s.
- `task_fields: []` is accepted by `string_list`. Every authenticated delivery then builds `task=''`, and the resolver rejects it as `invalid_input`. By then ingress has already stored the permanent replay tombstone, so the sender's retries are deduplicated onto a failed record. The same happens when every task field is optional and absent.
- **Fix:**
  - Add a cross-file check, used by both the CLI (when `--deployment` is given) and `register`/`create_platform_handler`, that resolves each route's auth profile, target and scope.
  - Require `task_fields` to be nonempty and to include at least one required field. Alternatively, reject an empty extracted task at ingress, before calling `reserve`.

**2. `unknown` and abandoned webhook rows are never bounded.**

- `retention_at` is set only on terminal states, and `abandon` only adds `disposition` while leaving the state as `unknown`. Such rows therefore:
  - stay in `Ledger.active()` forever;
  - are renewed and observed every 10 seconds;
  - keep their full task, context, registry snapshot and payload indefinitely.
- Separately, `WebhookService.owners` is never pruned, so it grows with every request handled by the process.
- This contradicts "bounded results/audit retention" in `docs/implementation.md`. The native adapter already handles this case correctly by erasing inputs of non-terminal rows after expiry.
- **Fix:**
  - Give abandoned rows (and `unknown` rows older than the retention window) a `retention_at`.
  - Exclude abandoned rows from `active()`.
  - Compact them like terminal rows, keeping the replay tombstone and `host_id`.
  - Remove `owners`/`jobs` entries once a row is terminal, abandoned or no longer active.

## Checked and not reported

- **Webhook authentication and replay:**
  - HMAC is computed over the raw body bytes and compared as bytes.
  - The secret, registry admission status and target are checked before the body is read and before any external call.
  - Replay is keyed on the full body digest within a per-route scope that must be unique.
  - Filters run on routing fields before reservation.
  - Payload values cannot choose the preset, model or effort.
- **Cancellation and ownership:**
  - Cancelling during resolve or selection bumps the generation, so the change to `starting` fails.
  - Shutdown cancellation during submit leaves a `starting` row with no `host_id`, which is recovered as `unknown` and never resubmitted.
  - A recovered `selected` row is safe to submit because no submit has happened yet.
- **Durable resolution:** restart resolution uses the durable registry snapshot. A target change before launch fails closed, as documented.
- **Rules and Jev:**
  - Rules: unique priorities, deterministic first match, explicit no-match handling.
  - Jev: finite choices, validated probabilities and confidence, bounded retries, and fallback only along configured edges with webhooks never using the parent LLM.
  - Jev receives only the projected fields, limited to the route's routing and task fields.
- **Native adapter:**
  - Preflight requires the exact verified provider/model/effort tuple, the per-launch effort marker, and either the fallback-control marker or an operator assertion that fallback is disabled.
  - The empty-toolset case is rejected.
  - Launch intent is persisted before invocation, and any exception becomes `unknown` without a retry.
  - Capability handles are removed from results, and redaction applies globally.
- **Packaging:** the entry point and wheel are correct.
- **Compatibility patch:** effort and fallback are validated at both the request and child-builder stages, and the parent and sibling runtimes are not mutated.

## Remaining deployment gates (already disclosed, not counted as defects)

- Whether the live `/v1/runs` honours `provider`, `model_options` and `instructions`.
- Whether the provider applies effort and actually disables fallback.
- Whether the host's native `status`/`cancel` enforces caller ownership.
- The real child-runtime ordering, which the patch tests stub out.

The fake host, provider and stubbed upstream tests do not establish any of these.
