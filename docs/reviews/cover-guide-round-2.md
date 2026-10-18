# Claude correction review — cover and configuration guide

Requested claude-opus-5-5 high; reported claude-opus-5-5; exit 0. Fresh no-tools review.

# Verdict: REQUEST_CHANGES

This review covers the supplied README, installation guide, configuration guide, `config.py`, `resolver.py`, `deployment.py`, `host.py`, `plugin.py`, `cli.py`, `systemone.py`, `jev.py`, `webhook.py`, `pyproject.toml`, `plugin.yaml`, the examples and the two evidence READMEs. I used no tools and did not inspect the cover image.

These were not supplied, so I make no claims about them:
- `ledger.py`
- the root `__init__.py`
- the Jev `registry.json` and `receipt.json`
- the Hermes host behaviour (`plugins enable`/`doctor` and the profile config layout)

The coordinator reported that the link, CLI, context and fragment checks pass; I did not re-run them.

All 15 findings from the previous review are resolved or acceptably addressed, except a residual inaccuracy in #12 (see P3-1). There is one remaining blocking issue.

## P2 (blocking)

**1. configuration-guide.md, starter pair 1: "After a successful spawn, call `orpheus_status`…" does not say what an unsuccessful spawn looks like or forbid retrying it.**
- `SubagentAdapter.launch` catches any exception raised by `lifecycle.launch` and returns normally with `{"state":"unknown","error":"launch_outcome_unknown"}`. The child may have been accepted anyway.
- That record has no stored handle, so `orpheus_status` and `orpheus_cancel` both return `{"error":{"code":"unavailable"}}`.
- A parent agent following this guide could reasonably treat that as a failure and spawn again. That risks a duplicate paid child, which contradicts the guarantee in installation.md that ambiguous submissions are not resubmitted.
- **Fix:** add a sentence such as: "Only `state: "running"` is an accepted launch. If spawn returns `state: "unknown"` (`launch_outcome_unknown`), do not spawn again or treat it as failed. Report the `request_id` for operator reconciliation, because status/cancel will report `unavailable` for it."

## P3 (non-blocking)

1. **Validate section:** "policy and route errors appear under `unavailable_policies` and `unavailable_routes`" is only partly true.
   - `unavailable_routes` lists only routes whose bound policy is unavailable.
   - These all fail top-level instead:
     - route structure (keys, `path`, `receipt`, unknown fields, filters, duplicate ID)
     - policy binding mismatches (unknown or mismatched `subagent_policy` or route policy)
     - deployment and reference errors (`missing_route_auth_profile`, `invalid_or_duplicate_route_security_scope`, `invalid_systemone_endpoint`, and so on)
   - Those top-level failures print `{"valid":false,"error":"<code>"}` with that specific code, not only `invalid_config`.
   - A YAML syntax error in the *deployment* file reports `source_unavailable`. A duplicate key reports `invalid_config`.
   - Suggest "for example `invalid_config`" plus one sentence on what `unavailable_routes` actually covers.

2. **`capability_reasons` reports only the first failing check per candidate,** because `preflight` raises on the first error.
   - With the starter deployment, discovery shows `unverified_fallback` but not `unverified_settings`.
   - Worth stating: "fixing one reason can reveal the next; recheck after each change."

3. **"Fixed or rule-selected setting IDs must exist in every reachable preset."** Add that a `parent` or `systemone` preset selector makes *every* registry preset reachable. That is the case that surprises authors who add a second preset under the starter's parent selector with a non-parent field resolver.

4. **"Webhook rule fields must be listed in `routing_fields`".** More precisely, they must be in the `routing_fields` of *every* route bound to that policy, because the rule schema is the intersection of those lists.

5. **System One projections not in a route's `routing_fields`/`task_fields`** pass offline validation if they are in `event_schema`. At runtime they are silently dropped from state, or they fail if listed in `required_fields`. The guide's "must also be in" is correct advice; noting that `validate` does not catch the omission would help.

6. **Data sent to System One:** the choice keys are preset IDs (preset stage) and tuple IDs (field stage). Add IDs to the list of fields to keep free of sensitive text.

7. **installation.md:** "the Resolver `systemone_client` argument/property". `systemone_client` is a plain instance attribute; only `jev_client` is a property. This is harmless for users and is wording only.

8. **installation.md, Jev evidence:** "selection through the subagent entrypoint" is not stated in the supplied `docs/evidence/jev/README.md`. Confirm it against `registry.json`/`receipt.json`, or drop "through the subagent entrypoint".

9. **Webhook pair:** "explicit loopback HTTP is available for local tests" should name the key, `allow_loopback_http: true` on the target.

10. **Offline validation gaps:** it does not detect native-incompatible presets (declared effort), `allowed_toolsets` missing from `subagent.allowed_toolsets`, or unverified pairs. A clause pointing agents to `orpheus_presets` capability reasons for these would close the loop.

## Verified against the supplied code

- **Stage-specific parent input:**
  - `preset_id` requires a top-level `parent` preset selector.
  - Any non-`None` `proposals`, including `{}`, requires a `parent` field resolver.
  - Parent preset plus System One fields accepts `preset_id` and rejects `proposals`.
  - Parent is rejected for webhooks.
- **Omission singleton:** omitted `proposals` (or `{}` under a parent resolver) matches every tuple, so it succeeds only with exactly one combination. Proposals use inventory references, and fixed overrides are rejected.
- **The guide's spawn examples:**
  - `{model: large}` resolves to `complex` and `{model: small}` to `routine`, against the starter preset.
  - The status argument shape matches `validate_id`.
- **Native limits:**
  - The 16000-character task and 32000-character context checks run after resolution and preflight, before persistence.
  - Context is the instructions block, the `Explicit task context:` block, the `\n\n` separators and `ensure_ascii=False` JSON. Only quote, backslash and control-character escaping expands it.
  - The schema default of 16384 is correctly bounded by the advice to set `max_length` to 16000 or less.
  - Oversized input can fail with `input_too_large` after a System One call.
- **Tool inheritance:**
  - A fixed nonempty list must be a subset of `subagent.allowed_toolsets`.
  - An omitted list inherits host toolsets, unconstrained by the deployment list.
  - An empty preset list is quarantined, and an empty list is also rejected in preflight.
  - Webhook targets reject toolsets.
- **Effort:**
  - Native effort is always rejected, with no `reasoning_effort` or `disable_fallback` sent.
  - Webhook effort requires the target's model `efforts`.
  - Tuple and fixed effort must be in the inventory `efforts`.
- **Secrets and deployment:**
  - A token-only override keeps the Typesafe endpoint.
  - A custom endpoint requires an explicit token variable (canonical or legacy).
  - Equal duplicate aliases are accepted; conflicting ones fail with code-only diagnostics.
  - The three renamed codes are correct.
  - Endpoints must be HTTPS with no userinfo, query or fragment, and redirects are disabled.
  - The System One payload description (projected state, purpose/guidance, merged candidate settings with provider/model) matches `resolver.py`.
- **Aliases:** `orpheus.jev.JevClient`, the `jev_client` argument and property, and the `DEFAULT_JEV_ENDPOINT`/`validate_jev_endpoint` re-exports all exist. `jev` is normalized in compiled policies while source and revision hashes are preserved.
- **Webhooks:**
  - All three body fields are required by default, and unknown `kind` values are rejected.
  - The path must equal `/orpheus/webhooks/<id>`.
  - Security scopes are unique per route, and operator Bearer tokens are scope-gated.
  - The HMAC is computed over the raw bytes, then the content type is checked.
  - Extra body keys (for example an event ID) are ignored by extraction, so the dedup advice is workable.
  - Receipts must be `disabled`.
- **CLI:**
  - The console script and `python -m orpheus.cli` are equivalent.
  - The CLI imports no aiohttp and makes no provider calls.
  - All four example validate/inspect commands should exit 0 with empty error mappings and `capability_status: unverified`.
- **Fragments:** the System One `field_resolver` blocks (README/installation and the guide's extended version), the OpenRouter deployment keys and the `context.operator_rules` schema example are all valid against `_policy`, `input_schema` and `systemone_settings`.
