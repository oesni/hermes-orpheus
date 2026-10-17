# Claude review — configurable Jev endpoint and live decision evidence

Requested claude-opus-5-5 xhigh; reported ['claude-opus-5-5']; exit 0. Source review only. The reviewer prompt reported the earlier 110-test run; the final 111-test run had already passed while this review was in progress.

# Independent review: hermes-orpheus changes since `ef58ab1`

**Verdict: REQUEST_CHANGES**

I read only the supplied source and evidence and ran nothing. Line numbers are counted from the supplied text.

There are no P0 or P1 findings. Two P2 issues and one verification gap block approval. The native-effort constraint is respected.

## P2

**P2-1: A credential can go to the wrong provider if only one Jev setting is changed.** `orpheus/deployment.py:62-65`, `orpheus/plugin.py:32-33`

`jev_endpoint` and `jev_token_env` have separate defaults, and validation accepts setting just one:
- Setting only `jev_endpoint` to OpenRouter sends `Bearer $TYPESAFE_API_KEY` to OpenRouter.
- Setting only `jev_token_env: OPENROUTER_API_KEY` sends the OpenRouter key to Typesafe.

The example comment says to replace both, but nothing enforces it. Disabling redirects doesn't help, because the first request already carries the header.

Fix: require the two keys together.

```python
if ('jev_endpoint' in value) != ('jev_token_env' in value):
    raise DeploymentError('jev_endpoint_requires_token_env')
```

The old example set `jev_token_env` alone. If that form must keep working, at least reject `jev_endpoint` without an explicit `jev_token_env`. Add tests for both one-sided forms.

**P2-2: The live evidence isn't bound to the code it claims to exercise, and `receipt.json` isn't the probe's raw output.** `docs/evidence/jev/README.md:3,15`, `receipt.json` → `operator_metadata`

- The README says "the production `Resolver` and `JevClient`" made the calls. The receipt pins only the probe hash. It has no hash or commit for `orpheus/jev.py`, `resolver.py`, `config.py` or `deployment.py`, which are all modified in this worktree. `jev.py` changed in this very delta (the endpoint parameter and `from None`), so which version ran is unrecorded.
- `jev_smoke.py:148` writes the report with `open('x')` and never emits `operator_metadata`. `final_probe_sha256` cannot have been produced by the tested probe. So the committed receipt was edited after the run, which the README doesn't disclose, and no digest of the original bytes exists.

Don't add hashes after the fact that weren't captured at run time. Pick one:
- **(a) Disclose.** If the raw output still exists, record its sha256. Move the operator metadata to a sidecar so `receipt.json` matches the probe output byte for byte. State that module hashes weren't recorded.
- **(b) Rerun.** Make the probe emit sha256 for itself and the four modules, plus `HEAD` and a dirty flag, then rerun. This incurs API usage, so it's your call.

## Required before approval: verify the final tree

The reported 110 tests / 53 subtests and the wheel/sdist build predate the final credential-CLI change. `tests/live/test_jev_smoke.py:20` (`test_custom_variable_name`) exercises the new `key_name` parameter, so it hasn't run as reported.

Re-run `uv run pytest -q` and `uv build` on the exact final tree and record the counts. `post_run_change` qualifies the live API run, not the offline suite.

I also can't verify that the `b29196a…` → `05811d…` probe change was CLI plumbing only. Present that as the operator's statement, or include the diff.

## P3

1. **The fixture can't detect a preset-to-tuple binding error.** `jev_smoke.py:29-33`
   - Both presets have identical `compatible_settings` and guidance. The second-stage candidates (`deep`, `quick`) look the same whichever preset was chosen.
   - Give `writer` distinct tuple IDs or mappings. Have the probe assert that the second call's `candidate_ids` match the selected preset's tuples.

2. **"Natural task descriptions" overstates the test.** `docs/evidence/jev/README.md:7`
   - The tasks carry cues that paraphrase preset purposes ("No code review is needed.", "This is documentation writing, not code review."). They also use complexity words that mirror the guidance.
   - Say "synthetic tasks with explicit domain and complexity cues" instead.
   - Extend `test_jev_smoke.py:28-38` to assert that preset IDs, tuple IDs and model refs are absent from the task text. They are absent today, but only `choose` and `effort` are checked.

3. **The top-level README overgeneralizes the live result.** `README.md:97`
   - The run was resolver-only, through the subagent entrypoint.
   - A native launch of a tuple with `effort` would be rejected; effort applies only to webhook routes.
   - The default Typesafe endpoint (`README.md:88`) was not exercised live.

4. **The endpoint validator accepts some malformed values.** `deployment.py:18-32`
   - Accepted cases:
     - `https://example.com:` (an empty port parses as `None`)
     - non-ASCII text, C1 controls and Unicode spaces such as `\u0085`, `\u00a0` and `\u2028` (the control check stops at ASCII)
     - DNS-invalid hosts such as `_`, `%` and `*`
   - Validation uses urllib while transport uses yarl, so the two parsers can disagree.
   - These appear to fail closed at request time with `service_unavailable`. I found no form that resolves to a different host. Still, a bad value should fail at load.
   - Fix: require `value.isascii()`, reject a netloc ending in `:`, and validate the host as an IP address or LDH labels. Optionally also require `str(yarl.URL(value)) == value`.
   - Add these cases to `tests/test_jev_endpoint.py:25-35`, and pin `https://@example.com`, which is currently rejected.

5. **Exceptions still retain some response data.** `jev.py:30,33`
   - `from None` hides the aiohttp error in tracebacks, but it is still kept as `__context__`.
   - On JSON failure, `from exc` keeps `JSONDecodeError.doc`, which is the full response body.
   - No path here carries the Authorization header, so risk is low. If nothing should be retained, set a flag inside `except` and raise after the block.

6. **Pre-existing, outside this delta.** `jev.py:42`
   - A list or dict `choice` raises `TypeError` rather than `SelectionError`.
   - Add an `isinstance(choice, str)` check.

7. **Probe nits.**
   - `jev_smoke.py:50-53`: `KEY="abc" # note` keeps the quotes. Strip the comment before the quote check.
   - `:148-149`: the file is created with umask permissions, then chmodded. Use `os.open(..., O_CREAT|O_EXCL, 0o600)`.
   - `:11`: the module-level `sys.path.insert` runs during pytest collection and can shadow an installed build. Move it under `__main__`.
   - No test ties `registry.json` and `operator_metadata.tasks` to `config()` and `CASES`. They match by hand today; add an equality test.

## Checked with no issue

- **Configuration:**
  - The endpoint and token reach the transport only through validated deployment settings.
  - The default endpoint is unchanged.
  - `allow_redirects=False`, and a 3xx response gives one call ending in `invalid_response`.
- **Errors:** `DeploymentError` and transport errors expose codes only, and the tests assert this.
- **Probe hygiene:**
  - It parses the dotenv value literally and rejects whitespace.
  - Failures produce a generic error code.
  - The response model is checked against an allowlist regex.
  - Task text never appears in call entries.
  - The endpoint and model are pinned.
- **Receipt and artifacts:**
  - Both stages are Jev: asserted offline, and visible as two calls per case with distinct candidate sets.
  - The receipt figures match the README: 8 calls, all HTTP 200, all `typesafe/jev-1.14-20261014`, confidence 0.94–1, 4/4 passed.
  - `registry.json` matches `config()`.
  - The artifacts contain no credentials or raw responses.
- **Effort:** the receipt scope and evidence README disclaim child execution and native effort application.

## Could not verify from the supplied material

- Any other `JevClient(` construction site, such as `orpheus/webhook.py`, must use the configured endpoint.
- `docs/implementation.md`, `docs/design.md` and the spec may still describe a fixed endpoint, or repeat the old "no Jev calls performed" text.
- `tests.test_plugin.Context` must set `state_dir` to a temporary directory. The wiring test clears the environment, so otherwise state would land under the real home directory.

## To flip to APPROVE

1. Fix P2-1 and add its tests.
2. Resolve P2-2 by disclosure or a rerun.
3. Re-run the suite and build on the final tree and record the results.
4. I'd also include P3-3, which is a one-sentence doc fix.
