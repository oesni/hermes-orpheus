# Claude review — local fixed-preset webhook smoke

Requested claude-opus-5-5 high; reported ['claude-opus-5-5']; exit 0. Source-only no-tools review.

# Independent review: webhook fixed-preset smoke delta since `10d13fc`

**Verdict: REQUEST_CHANGES.** There are no P0 or P1 defects. Four P2 findings remain. Three are evidence claims that say more than the code or artifacts establish. One is a fail-open path in the verifier.

The harness design itself is sound:
- It uses the production `WebhookService`, `Resolver`, `Ledger` and `RunClient` behind real signed HTTP.
- The HMAC secret, operator token and adapter token stay in memory, environment variables or an owner-private 0700 directory.
- The receipt contains no secrets or raw model output.
- Unsigned delivery, unauthenticated status reads, per-scope replay deduplication and the exact-key payload check are real checks.

Review basis: source reading only. I ran no tests and did not check any recorded hash against the files.

## P2 findings

**P2-1. `bootstrap-receipt.json` does not record what the README says it records.**
- In `hermes_api_bootstrap.py`, `stopped`, `real_adapter` and `full_gateway_started` are constants. The only computed field is `before==after`.
- The README says the receipt records:
  - "successful adapter shutdown", but the return value of `adapter.disconnect()` is never checked or recorded;
  - "removal of its active connection file", but `unlink` runs and nothing records it;
  - "unchanged hashes for five protected … files", but `fingerprint()` returns `None` for a missing path. A missing file therefore counts as "unchanged", and `protected_configuration_files` counts paths, not files that exist.
- The fifth path, supplied via `--protected-file`, is not identified anywhere.
- The receipt has no timestamp, PID or port, and `operator-metadata.json` does not hash it. Nothing in Git ties it to this run.
- "The owning bootstrap process exited successfully" appears in no artifact.
- **Fix:** either reword the README to "operator-observed", or have the receipt record per-path existence, the disconnect outcome, connection-file absence after unlink, and a run identifier.

**P2-2. "Exact launch payload matched configured instructions" overstates the oracle.**
- `webhook_preset_smoke.py` compares `call['payload']['instructions']` to `selected['instructions']`, which is the resolver's own output. It never compares against the fixed instruction string built by `config()` for that preset.
- The live harness also never asserts that `payload-override` is absent. Only the fake-upstream test does.
- The marker check (`preset_marker == name`) does give independent, indirect evidence that the preset's instructions reached the model. So this is an over-claim of the oracle, not evidence that selection was wrong.
- **Fix:** assert `payload['instructions'] ==` the configured instruction for `name`, plus the absence of `payload-override`. Otherwise reword `WEBHOOK.md` ("proves none changes") and the README ("matched configured … instructions").

**P2-3. The "distinct new sessions" check adds nothing beyond distinct run IDs, and "new" is not verified.**
- In `receipt.json`, `session_id == host_id` for both cases.
- `assert len(set(sessions)) == 2` is therefore implied by the distinct-host-ID assertion just before it.
- Freshness rests on an inference: no session field in the payload, and the session ID equals a fresh run ID. That is reasonable, but it is not an observation that no prior session or history was used.
- Since a new session was the user's stated goal, either qualify the claim ("distinct run-scoped session IDs; no session field submitted") or add a discriminating check, such as a native status or history field showing a single-turn fresh session.

**P2-4. Every verification in the live harness is a bare `assert`.**
- Under `python -O` or `PYTHONOPTIMIZE`, every check in `run()` and `finding()` is removed, and `main()` would write `passed: true`.
- The recorded receipt is not affected, assuming it was run without `-O`. It is still a fail-open verifier.
- **Fix:** use explicit `if not …: raise SmokeFailure(code)`, or refuse to run when `sys.flags.optimize` is set.

## Notes (not blocking)

- **Hash binding:** fixing P2-2, P2-3 or P2-4 in `tests/live/*.py` changes the files hashed in `operator-metadata.json`, which breaks the tie between the receipt and the source.
  - Fixing P2-1 by rewording the README needs no rerun. Fixing it in code changes `hermes_api_bootstrap.py`, which is also hashed.
  - **Recommendation:** fix the wording now and keep the tested harness bytes as they are. Do any harness hardening as a follow-up with a new live run and new metadata.
  - In either case, recompute all seven file hashes and `receipt_sha256` before committing. I did not verify them.
- **Possible reconcile race:** the harness drives observation through `POST …/reconcile`, which calls `ledger.claim()` and then `observe(_recovered=True)`.
  - If `claim()` can take a row whose `process()` is still inside `submit()`, a `starting` row without a host ID becomes `unknown`.
  - This fails closed: the assertion fails, and `cancel_unfinished` cancels any recorded run ID. It cannot produce a false pass.
  - I could not see the `claim()` semantics in `ledger.py`. Worth confirming, because a plain authenticated GET does not observe the host.
- **Orphaned submissions on failure paths:** an in-flight submission that is accepted upstream but never recorded is not cancelled and prints no notice. This can happen when app cleanup cancels the task mid-`submit`. Consider printing `cleanup: unrecorded_submission` for `calls` entries that lack `run_id`.
- **Negative tests:** `test_webhook_preset_smoke.py` has none for the headline claims. There is no case for a duplicate session, a swapped marker, or a resolver passing payload instructions through. The verifier's ability to discriminate is only shown for `finding()`.
- **Wording:**
  - "Unsigned requests were rejected": one unsigned request was sent, to `reviewer` only.
  - "unmodified local Hermes runtime": no artifact records a clean-tree check at `d923a5eb`.
  - `verifier_exit` does not say which process it refers to.
  - Opening the README with "performed real model inference using the … provider" states as fact what the README later correctly qualifies as final-runtime metadata.
- **Doc delta:** the `jev_endpoint` paragraph documents the `10d13fc` feature, not this delta. That is fine, but it is unrelated scope.
- **Before committing `docs/evidence/webhook-preset/`:** list its complete contents to confirm that no `connection.json`, `stop` file or runtime log was copied in alongside the four reviewed files.
