# Claude review — core-unmodified scope

Requested claude-opus-5-5; reported ['claude-opus-5-5']; exit 0. Reviewed scoped diff and full selected implementation/test files; no execution.

**Verdict: APPROVE.** I found no P0, P1 or P2 defects in the material you supplied.

I reviewed the diff and the full files you selected. I used no tools and ran nothing, so this confirms nothing about pytest, `uv build` or live provider behaviour.

**Code**
- **No effort can reach a native child.** `preflight` rejects any `effort` key in every case, whatever the host advertises (`host.py`). `capabilities()` no longer probes the lifecycle, and the test checks that the probe counter stays at 0. The request contains only `goal/model/provider/correlation_id/metadata/context/allowed_toolsets`, so `reasoning_effort` and `disable_fallback` can never be sent.
- **Fallback fails closed.** Launch requires `fallback_disabled is True` in the deployment file. There is no path that enables it through a capability probe.
- **Deployment schema:** `validate_subagent` now accepts only `{provider, model}`, and an `effort` key is a validation error. The test covers both the rejected and the accepted shape.
- **Candidate selection:** the `{"model":"large"}` proposal matches exactly one tuple (`complex`). Both concurrent stock launches go out with different models and different correlation IDs.
- **Discovery:** presets that declare effort (for example, webhook presets) show up in subagent discovery as `unverified` with `unsupported_effort`. They are not silently accepted, and spawning one fails before any host call.
- **Original `inventory/fields/compatible_settings/policies` schema:** unchanged. Webhook model/effort selection through the Run API is untouched in the material shown.

**Minor fixes (P3)**
1. `README.md`, install section: the line "intentionally denies execution until an operator verifies the exact provider/model/effort settings" contradicts the native `{provider, model}` scope. Change it to "native provider/model settings and webhook provider/model/effort targets".
2. `docs/feasibility.md`, options table: the upstream-extension row still says "Preferred clean contract", while the section heading now calls it deferred research. Reword it to something like "Deferred: clean contract if native effort is later in scope".
3. `tests/test_plugin.py`: the name `test_original_example_loads_and_reports_effort_gate` is now stale, because the test checks `effort: unsupported` and `unverified_fallback`. Rename it, for example to `..._reports_native_gates`.
4. Optional: `orpheus validate --deployment` doesn't warn when a preset reachable from the subagent policy declares effort. Today that only shows up at discovery or spawn time. A validation warning would match the README instruction "Omit `effort` from native preset fields".

**Not shown, so not verified (check before merge)**
- Nothing still refers to `compat/` or the patch test: check `pyproject.toml` build includes and sdist/package-data, pytest `testpaths`, and any links in `docs/reviews/README.md` or `docs/evidence/`. A dangling build include would break `uv build`.
- `examples/webhook-deployment.yaml` must not contain `subagent.verified_settings` entries with `effort`, which are now invalid. `CrossFileCliTests` would catch this only if it runs.
- `orpheus/webhook.py` and anything else must not read the removed `capabilities()` keys `effort_contract` or `fallback_control`.
- `docs/design.md` examples and the traceability rows for requirements 10–12 must not still describe native effort selection. The new note limits effort-bearing examples to the webhook path, but I didn't see the body.
