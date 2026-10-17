# Claude correction review — fixed-preset webhook smoke

Requested claude-opus-5-5 high; reported ['claude-opus-5-5']; exit 0. Source-only no-tools review.

# REQUEST_CHANGES

This is a source-only review of the diffs you supplied. I ran no tools and executed nothing. P2-1, P2-3 and P2-4 are resolved. P2-2's runtime oracle is correct, but its mutation regression does not discriminate.

## P2-2: mutation regression passes even if the probe oracle regresses

**Location:** `tests/live/test_webhook_preset_smoke.py`, `test_fixed_route_http_probe[True]`

**Problem:** In the corrupted case, `pytest.raises(AssertionError)` wraps the whole `scenario()`. That includes the test's own checks after `probe.run`:

```python
assert all('payload-override' not in json.dumps(call) for call in calls)
```

Suppose the probe reverts to comparing against `selected['instructions']` and drops the new absence check. Then `run` returns `passed=True`, and this test-side line raises the expected `AssertionError` instead. The test still passes, so it does not prove that `run` itself rejects an altered launch payload, which is the point of P2-2.

**Fix:** Restrict the expected failure to the `probe.run(...)` await inside `scenario`. For example, in the corrupted case put `with pytest.raises(AssertionError): await probe.run(...)` around only that call, and skip the post-run assertions. Alternatively, inspect the traceback to confirm the failure came from inside `probe.run`.

The runtime change itself is sound:
- The expected value is read from the `source` config, independent of `Resolver`.
- The `'payload-override'` absence check is correct.
- The monkeypatch on the shared `Resolver` class does reach the webhook path.

## Resolved

- **P2-1:** The README now states only what `bootstrap-receipt.json` can support: the cleanup code completed and the fingerprints were equal, with the null-for-missing caveat. Process exit, connection-file removal and Hermes checkout cleanliness are now labelled as operator observations in the metadata sidecar. The receipt hash is bound.
- **P2-3:** The key was renamed to `distinct_run_scoped_session_ids_verified`, the README describes the omitted reuse fields, and the freshness inference is qualified as "no independent history inspection."
- **P2-4:**
  - Bootstrap refuses at import.
  - The smoke script refuses at `main`, `run` and `finding`.
  - `PYTHONOPTIMIZE` is covered by `sys.flags.optimize`.
  - The `-O` and `-OO` subprocess tests cover both the CLI and direct `run`.
  - A missing import in the subprocess would make the test fail, not falsely pass.
- **Evidence hashes:** The three harness hashes and the receipt hash were updated, and the product hashes are unchanged. This is consistent with no product runtime edits.

## Non-blocking notes

1. **Bootstrap receipt provenance:**
   - `bootstrap-receipt.json` is byte-unchanged, but the bootstrap source changed (`c795…` → `aa52…`) and four model runs exist in total.
   - The metadata does not say which bootstrap invocation produced this receipt.
   - Say that it came from the adapter session of the final hardened run, or explain why it is byte-identical across invocations, for example because it contains no timestamps or source hash.
2. **Stale key in `docs/implementation.md`:** That file's hash is unchanged. Confirm it does not cite `distinct_new_sessions_verified` or claim "new sessions" without qualification.
3. **No bootstrap optimization test:** The bootstrap `-O` refusal has no subprocess test. It is a trivial import-time guard, so this is optional.
