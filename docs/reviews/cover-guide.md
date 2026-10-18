# Claude review — cover and configuration guide

Requested claude-opus-5-5, high effort; reported claude-opus-5-5; exit 0. Fresh no-tools review of supplied public documentation and contracts. Image identity checked locally; no image inspection claimed by reviewer.

# Verdict: REQUEST_CHANGES

This review covers only the supplied text and source: README, installation, configuration guide, `config.py`, `resolver.py`, `deployment.py`, `host.py`, `plugin.py`, `cli.py`, `systemone.py`, the examples and `plugin.yaml`. I did not inspect the cover image. The webhook module, pyproject and the evidence READMEs were not supplied, so I make no claims about webhook auth/HMAC/URL handling, the console script, or the smoke-test results. I used no tools.

## P1

**1. installation.md, Subagents: "Tool access cannot exceed the verified deployment scope."**
- This is false whenever a preset omits `allowed_toolsets`.
- `SubagentAdapter.preflight` checks the subset against `subagent.allowed_toolsets` only `if 'allowed_toolsets' in settings`. Otherwise the request omits it and the child inherits the host/parent toolsets, unconstrained by the deployment list.
- The starter `analyst` preset omits it, so this claim misstates the security boundary for the documented example.
- **Fix:** "When a preset fixes `allowed_toolsets`, every entry must also appear in the deployment's `subagent.allowed_toolsets`. If the field is omitted, the child inherits host/parent toolsets and the deployment list does not limit it."

## P2

**2. configuration-guide.md: the deployment key `subagent.allowed_toolsets` is never named.**
- The table says "within operator **and parent** permissions", but no step tells the operator which key holds the operator permission.
- The example deployment sets `allowed_toolsets: []`, so any preset that adds a fixed toolset fails with `unauthorized_tools`.
- **Fix:** In starter pair 1, add: "If you fix `allowed_toolsets`, list the same toolsets in `subagent.allowed_toolsets`. Omitting the preset field inherits host tools; see the note above."

**3. configuration-guide.md and installation.md: native size limits are missing.**
- `host.launch` rejects a task over 16000 characters. It also rejects rendered context over 32000 characters, where rendered context is the `Preset instructions:` block plus the JSON-encoded `context`.
- The guide's own example, `context.operator_rules` with `max_length: 20000`, can exceed 32000 once combined with the instructions and JSON escaping. Many newlines or quotes are enough.
- This check runs after resolution, so a System One field selection may already have been paid for before `input_too_large` is returned.
- The schema default for `task.text` with no `max_length` is 16384, which is above the native 16000 cap.
- **Fix:** State both caps. Advise `task.text.max_length ≤ 16000` and context bounds that leave room for instructions and JSON escaping. Note that oversize input fails after selection.

**4. installation.md: "The System One client receives only configured context projections and finite choices."**
- This understates what leaves the host. In `resolver.py`, the preset stage sends each preset's `purpose` and `guidance`. The field stage sends the selected preset's `purpose` and `guidance` plus fully merged settings for each candidate: fixed `instructions`, `allowed_toolsets`, and the real `provider`/`model` identities.
- The guide states this correctly ("keep secrets out of purpose, guidance, instructions…"); installation.md should match it.
- **Fix:** "…projected inputs plus the choice descriptions: preset purpose/guidance and each candidate's resolved settings, including fixed instructions and provider/model identities."

**5. Both documents: a token-only override sends the credential to Typesafe.**
- `systemone_settings` accepts `systemone_token_env` alone and keeps the default `https://api.typesafe.ai/v1/systemone`. Setting only `systemone_token_env: OPENROUTER_API_KEY` therefore sends the OpenRouter token to Typesafe.
- installation.md mentions only "Legacy token-only overrides retain the default Typesafe endpoint", which reads as legacy-only. The guide's "set these together" is advice, not a stated consequence.
- **Fix:** "Setting only `systemone_token_env` (canonical or legacy) keeps the Typesafe default endpoint and sends that credential there. Always change both keys together for another provider."

**6. configuration-guide.md: "Parent proposals must identify exactly one compatible combination; missing or ambiguous proposals fail."**
- When `proposals` is omitted, the resolver uses `{}`, which matches every tuple. With exactly one compatible combination, an omitted proposal succeeds.
- **Fix:** "…missing proposals succeed only when the preset has a single combination; otherwise missing or ambiguous proposals fail."

## P3

**7. Inconsistent CLI invocation.**
- README uses `uv run orpheus …`; the guide uses `python -m orpheus.cli …`.
- The console script cannot be verified from supplied material.
- **Fix:** Use one form, or state that both are equivalent. `python -m orpheus.cli` from the checkout needs only PyYAML.

**8. installation.md: "Rules/System One policies reject parent overrides."**
- Fixed selectors also reject them (`preset_id`/`proposals` with a non-`parent` kind).
- **Fix:** "Fixed, rules and System One policies reject `preset_id`/`proposals`."

**9. installation.md: "registers discovery tools with an empty registry."**
- All four tools are registered.
- Loading also creates the state directory and SQLite file and starts a retention thread. That does not contradict "never launches work".
- **Fix:** "registers the Orpheus tools over an empty registry."

**10. installation.md: "The preset example uses the original interface."**
- The phrase is ambiguous.
- **Fix:** "…uses parent-selected native subagent presets."

**11. installation.md says the guide "covers … the first discovery/spawn/status check"; the guide never shows `orpheus_status`.**
- **Fix:** Add a step to the guide: call `orpheus_status` with the returned `request_id`.
- It would also help to note that `orpheus_presets` reports `execution_capability` and `capability_reasons`, such as `unverified_settings`, `unverified_fallback` and `unsupported_effort`. That is the quickest way to diagnose a blocked launch.

**12. configuration-guide.md, Validate: some errors give no location.**
- Top-level structural errors print only `{"valid": false, "error": "<code>"}`, such as `invalid_config`, without saying where.
- Per-preset errors appear under `quarantined`, and policy/route errors under `unavailable_*`.
- **Fix:** Note this so agents know where to look.

**13. configuration-guide.md, adding a dedicated reviewer route: two missing requirements.**
- A second route that reuses the same `auth_profile` needs a distinct route-level `security_scope`, because scopes must be unique across routes. A separate auth profile also works.
- The operator token's `operators` entry must be granted the new scope.

**14. configuration-guide.md, webhooks: deduplication consequence.**
- The example deployment says raw-body digests are retained indefinitely and identical legitimate events collapse.
- **Fix:** Tell senders that distinct events must differ in body bytes.

**15. installation.md: "the old Python names remain compatibility aliases."**
- Supplied code confirms `jev_client` (Resolver kwarg/property), `DEFAULT_JEV_ENDPOINT` and `validate_jev_endpoint`. These live in `orpheus.deployment`, not `orpheus.systemone`.
- No `SystemOneClient` alias, such as `JevClient`, appears in the supplied `systemone.py`.
- **Fix:** Confirm the alias exists elsewhere, or narrow the sentence to the names listed above.

## Verified as accurate against the supplied code

- **Native effort:** `preflight` rejects any `effort` with `unsupported_effort`. The request never carries `reasoning_effort` or `disable_fallback`. Effort is rejected even when it comes from inventory or a tuple.
- **Launch gating:** `fallback_disabled: true` and an exact `{provider, model}` in `verified_settings` are both required. An empty `allowed_toolsets` list is rejected in config and in preflight.
- **Fields:** `instructions` and `allowed_toolsets` are fixed-only. Tuples must cover all enum fields. Tuple efforts must be in the inventory `efforts`. `parent` is native-only. A non-parent kind rejects `proposals: {}`.
- **Rules:** unique integer priority, ascending order, first match wins. Fixed and rule-selected setting IDs must exist in every reachable preset. 255-choice cap.
- **Alias handling:** `jev` is normalized in compiled policies while source and revision keep the original. Equal duplicate keys are accepted; conflicting ones fail with codes only. A custom endpoint requires an explicit token env. The three renamed diagnostic codes are correct. HTTPS only, no userinfo, query or fragment, redirects disabled.
- **Webhook example:** All three body fields are required by the webhook default. Unknown `kind` values are rejected. Mapping is routine→small/low and complex→large/high. The `path` must equal `/orpheus/webhooks/<id>`. Receipts are `disabled` only.
- **CLI:** No provider calls. `validate` and `inspect` output keys match the guide's expectations, including exit 1 on quarantined or unavailable entries and `capability_status: unverified`.
- **Snippets:** The System One YAML fragments are valid against `_policy` and `systemone_settings`. The spawn argument object matches the tool schema.
