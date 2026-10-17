# Claude implementation review — round 1

Requested model `claude-opus-5-5`; reported models ['claude-opus-5-5']; CLI exit 0. Full supplied source snapshot, no tools.

I reviewed every supplied file except the hash-pinned vendor fixtures under `compat/upstream/`, which are vendor source rather than first-party code. I made no edits and ran nothing. Approval would cover the source only; it would not certify production or provider behavior.

**Verdict: REQUEST_CHANGES.** There are two P2 defects in webhook lifecycle ownership and five P3 items below.

## P2

**1. An operator reconcile during submission loses the host run (`webhook.py` `WebhookService.operator` → `observe`, and `process`).**
- **Trigger:**
  - `process` moves the row `selected→starting`, then awaits `host.submit` for up to 25 seconds.
  - During that wait, an operator calls `POST /orpheus/requests/{id}/reconcile` with an empty body.
  - `ledger.claim` returns `None` because the lease is still valid, so `observe` runs on the current row.
  - `observe` sees `starting` with no `host_id` and successfully calls `change(…,('starting',),'unknown')`. The generation matches and the lease is valid.
  - When `submit` returns, `change(('starting',),'running',host_id=…)` fails. Its return value is ignored, so the `host_id` is discarded.
- **Result:** A live Hermes run exists but cannot be tracked. It can never be observed, cancelled or have its result retrieved. Abandoning the record only hides it. The same loss happens if the lease lapses mid-submit, for example when renewal stops (see P3-1).
- **Fix:**
  - `observe` should convert a host-id-less `starting` row to `unknown` only when no local job owns the request (`rid not in self.jobs`) and the caller actually won `claim` on an expired lease.
  - Publishing `host_id` after a successful submit should not depend on the lease. Write it with an update keyed on the idempotency key that accepts `starting` or `unknown`.
  - If that write fails, record and surface the failure instead of returning silently.

**2. Any later edit to a target permanently strands launched webhook runs (`webhook.py` `observe`).**
- **Trigger:** An operator edits `targets.<id>` in the deployment file and restarts Hermes. Example edits: adding a model to the allowed set, rotating `token_env`, or toggling `verified`. After that, `row['target_snapshot'] != target` is true for every in-flight row.
- **Result:**
  - `observe` returns silently on every reconcile pass.
  - A pending `cancel_requested` is never forwarded.
  - Status and results are never fetched, and the row stays `running` indefinitely.
  - `abandon` only accepts `unknown`, so the operator cannot clear the row.
- The documented rule is "Target changes cannot reselect an admitted delivery." That rule covers reselection before launch, which `process` already enforces. It should not block observing or cancelling a run that has already been accepted.
- **Fix:** Bind observation and cancellation to the host identity actually used for the run (origin plus principal), not to equality of the whole target configuration. If that identity truly changed, record an explicit `observation_unavailable` / `target_changed` error and allow administrative disposition.

## P3

**1. The reconcile loop has no error isolation (`webhook.py` `reconcile`).** Any exception kills the only renewal, recovery and expiry task for the rest of the process lifetime. Examples:
- `sqlite3.OperationalError` ("database is locked") once the 5-second `busy_timeout` is exceeded, for instance when two workers share `state_dir`;
- a JSON decode error in `expire_results`.

After that, leases stop renewing, so the in-flight `change` calls in `process` start failing (feeding P2-1). Restarted rows are also never recovered. **Fix:** catch and log errors per iteration and per row, and keep the loop running.

**2. Unsupported or inconsistent configuration is accepted at load and `validate` time.** Each case below should be rejected in `Registry.__init__`/`_policy` or the `WebhookService` constructor, or by a strict deployment schema:
- `config.input_schema(webhook=True)` accepts `source: header` and `trust: verified_metadata`. Every delivery is then rejected only at runtime by `extract`, while `orpheus validate` reports the file as valid. The implementation notes explicitly say these "must not be silently accepted."
- A route whose `policy` key does not exist is never checked. Ingress admits the body and consumes its permanent replay tombstone, and `process` then fails with `policy_unavailable`. After the configuration is fixed, the sender's retry is deduplicated to that failed record.
- A `subagent_policy` that names a missing policy, or a webhook-entry policy, also passes `validate`.
- The deployment YAML has no schema validation:
  - A typo such as `redact_literal` silently disables redaction.
  - `operators` values are not checked to be lists. A string value turns `row['scope'] in scopes` into a substring match, which can grant extra scopes.
  - `verified_settings` entries are not type-checked.

**3. `routing_fields` is not enforced for rules or filters (`config._policy`/`_predicate`, `resolver.matches`).** The webhook rule schema is the full `event_schema`, and the resolver matches against every extracted value. A rule or filter on a `task_fields`-only payload field (for example `event.description`) is therefore accepted and influences selection. Only Jev projection respects `routing_fields`. The requirements say routes declare their "permitted routing inputs." **Fix:**
- Validate the field references in route filters and in the rule predicates of each policy those routes use against `routing_fields`.
- Build the resolver's matching `values` from `routing_fields` only.

**4. `redact_literals` is read from different places on the two entry points.** `SubagentAdapter` reads `deployment['subagent']['redact_literals']`, while `WebhookService.observe` reads the top-level `deployment['redact_literals']`. `docs/implementation.md` documents a single optional top-level key. An operator who follows the docs therefore gets no redaction of native child results. **Fix:** use one documented location, applied to both entry points, or reject the misplaced key.

**5. Retention and file privacy are unbounded and leaky (`ledger.py`, `host.py`, `plugin.py`).**
- Every webhook row permanently stores the full `registry_snapshot`, the task text, the extracted payload context and the submitted `payload`. Only `result` expires. The native `children` table is never pruned either. This contradicts "bounded results/audit retention" for sensitive inputs.
- `expire_results` and `SubagentAdapter._owned` scan the entire table every 10 seconds or on every call, so the cost grows without limit.
- `mkdir(mode=0o700, exist_ok=True)` does not tighten an existing directory.
- Only the main database file is chmodded. The WAL file (`webhooks.sqlite3-wal`) and the shared-memory and journal files are created under the process umask, so payloads and results can be world-readable under a pre-existing 0755 state directory.

**Fix:**
- After a run is terminal and its retention period has passed, compact the row to a tombstone (`id`, `scope`, `digest`, final `state`, `disposition`).
- Prune native rows on the same schedule.
- Set the umask to 0077 around opening the databases and verify the directory's mode on startup.

(Minor, same area: `hmac.compare_digest` on a non-ASCII signature header raises `TypeError` and returns HTTP 500 without an audit record. Compare encoded bytes instead.)

## Checked and not reported

These did not need changes:
- The HMAC is computed over the raw body bytes; replay is keyed on the full body digest within a per-route scope that the constructor requires to be unique.
- Cancellation before launch bumps the generation and fences late selection.
- Restart turns a host-id-less `starting` row into `unknown` without resubmitting.
- Webhook resolution uses the durable registry snapshot from admission.
- Selection policy is enforced per entry point: webhooks reject parent-LLM selection, and preset/field proposals are rejected under rule or Jev policies.
- Jev uses finite choices, validates probabilities and confidence, and allows only configured fallback edges.
- Native preflight requires an exact verified tuple, the per-launch effort capability marker and either fallback control or an operator assertion that fallback is disabled.
- Capability handles are stripped from returned results.
- The entry point and wheel packaging are correct.
- The patch validates effort and fallback on both the request and the child-builder sides.

Three things remain deployment gates that the docs already disclose: whether the live `/v1/runs` honours `provider`, `model_options` and `instructions`; whether `instructions` replaces inherited profile rules; and the real child-runtime ordering, which the patch tests stub out.
