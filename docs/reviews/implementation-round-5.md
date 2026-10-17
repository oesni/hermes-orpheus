# Claude implementation review — round 5 (delta)

Requested model `claude-opus-5-5`; reported models ['claude-opus-5-5']; CLI exit 0. Focused correction review. Unchanged files inherit the round-4 source review by exact SHA256 equality; changed files supplied in full: orpheus/ledger.py, orpheus/webhook.py, tests/test_ledger.py, tests/test_webhook.py.

# Delta review — round 5 (final correction)

I reviewed the four changed files against the round-4 report. I used no tools and executed nothing. The tests use a fake host and stubbed upstream, so they do not certify real providers or the real Hermes host.

**Verdict: APPROVE. I found no defects in the delta.** The remaining round-4 P3 is resolved in both its cases.

## Round-4 P3: resolved

### Case (a): a failed acceptance publication left the row stuck in `starting`

1. **What happens to the failure inside `process`.**
   - `publish_acceptance` raises, the error is logged and re-raised, and the outer `except Exception` catches it.
   - That handler's change to `failed` only accepts rows in `resolving` or `selected`, so it does not apply. The row stays in `starting`.
   - The exception is swallowed there, so the job task ends normally and the `finished` callback removes it from `self.jobs`.
2. **What the reconciler does next.** On its next pass the row matches the new branch: the owner's generation matches, the job is gone, the state is `starting` and there is no `host_id`. The reconciler changes the row to `unknown` with code `dispatch_completion_unconfirmed`, removes the owner entry and moves on. An `unknown` row can be abandoned, so no restart is needed.
3. **No race with a live submit.** The reconciler's loop body has no `await`. `schedule` adds the job to `self.jobs` synchronously, and the job is only removed from that callback. So a submit that is still running is always in `jobs` and is skipped. `test_reconciler_does_not_steal_live_starting_owner` covers this for both a local owner and another process's live lease.
4. **If the lease has already expired.** The direct change to `unknown` then fails, and so does `renew`.
   - The code does not `continue` in that case, so it falls through to `claim`. `claim` increments the generation and marks the row `_recovered`.
   - `observe` then hits its existing branch for a recovered `starting` row without a host ID and changes it to `unknown`.
   - This means a stalled event loop cannot leave the row stuck either.
5. **Shutdown and restart.**
   - `close` cancels the jobs and the reconciler together. The reconciler is waiting in `sleep` and never resumes its loop body, so it cannot run the new branch on a half-closed service.
   - After a restart `owners` is empty, so recovery goes through lease expiry, then `claim`, then `observe`, as before.
6. **The new test.** `test_ended_dispatch_publication_failure_becomes_abandonable` checks:
   - the row ends in `unknown` with `dispatch_completion_unconfirmed`;
   - the host was called exactly once (no resubmission);
   - `owners` and `jobs` are empty;
   - the row can be abandoned.

### Case (b): rows with no host ID cost work forever

- `active()` now leaves out `unknown` rows whose `host_id` is empty or missing. Each pass prunes `owners` to the active IDs, so these rows cost no renew writes and no scheduled tasks.
- **A late acceptance still works.** It only happens when a recovered owner marks the row `unknown` while the original submit is still running. That dispatcher's `publish_acceptance` accepts a row in `unknown`, moves it to `running` and records the host ID, so the row is in `active()` again.
  - `test_unknown_without_host_id_is_not_polled_but_late_acceptance_reactivates` covers this.
  - So does the existing test `test_reconcile_while_submit_and_late_acceptance_survives_new_owner`, which also carries `cancel_requested` through to the owned stop.
- **Retention is unchanged.** Changing a row to `unknown` sets `retention_at`, and compaction keeps the dispatch evidence (`dispatch_token`, `idempotency_key`, `payload_digest`, the target identity and the receipt row).

## Delta regression check (nothing found)

- **Fencing:** the new reconciler transition still goes through the generation- and lease-guarded `change` and only accepts `starting`. It cannot override a terminal row, a cancelled row or a row with a host ID.
- **Cancellation:**
  - `Ledger.cancel` on a `starting` row keeps the generation, so the same owner can still change it to `unknown` and `cancel_requested` is preserved.
  - Abandoned rows are still left out of `active()`.
- **Exclusions from round 4 still hold:** `unknown` rows with `host_run_unavailable` or `target_identity_changed` are still left out, and a transient failure still keeps the row `running`.
- **Security:** none of the ingress, HMAC, replay, operator authorization or response-field code changed.
- **SQL predicate:** a host ID is always a non-empty string or absent, and compaction keeps `host_id`. So the `COALESCE(json_extract(...),'')=''` test does not wrongly leave out a row that has a host ID.

## Non-blocking note (not a finding)

Case (a) has a residual limit. When the database fails after the host has accepted the run, the host run ID exists only in the log. The durable row ends as `unknown` with no `host_id`, so an operator can abandon it but cannot cancel or observe that host run through Orpheus.

This is the expected result when the database itself fails, and the log line names both IDs. Optionally, `process` could make one more best-effort `change(...,'unknown',host_id=...)` attempt after the failed publication. That is not required for approval.

## Remaining deployment gates (unchanged)

These are the same five gates disclosed in round 4. The fake host, provider and stubbed upstream tests do not establish any of them:

- Whether the live `/v1/runs` honours `provider`, `model_options` and `instructions`.
- Whether the provider actually applies effort and disables fallback.
- Whether native `status`/`cancel` enforces ownership.
- Whether `register_platform_handler` mounts the routes before the aiohttp app freezes.
- Whether the API server's authentication middleware lets unauthenticated webhook ingress through.
