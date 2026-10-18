# Claude final review — cover and configuration guide

Requested claude-opus-5-5 with CLI effort high; reported claude-opus-5-5; exit 0. Fresh no-tools correction review. Unchanged implementation and asset hashes were checked locally against round 2.

# Verdict: APPROVE

This was a narrow correction review of the supplied deltas and current text for the README, installation guide and configuration guide. I checked them against the supplied `host.py` and `ledger.py`. I used no tools, ran no tests and did not inspect the cover image. The coordinator reported that the link, CLI, context and fragment checks pass; I did not re-run them. The implementation-hash check was reported by the coordinator, not verified by me. The reported model is `claude-opus-5-5`; I cannot independently confirm the effort setting.

## P2: unknown-launch handling is resolved

The new configuration-guide paragraph matches `SubagentAdapter`:
- If `lifecycle.launch` (or `plain`) raises, the row is set to `unknown` with `handle` left NULL. The adapter then returns `{"state":"unknown","error":"launch_outcome_unknown"}`. The guide quotes both values exactly.
- With a NULL handle, `_owned` raises `HostError('unavailable')`, so status and cancel report `unavailable`. The guide says this and correctly states that it is neither proof that no child exists nor permission to retry.
- "Do not spawn again or classify it as failed" closes the duplicate paid-child risk. It is consistent with the installation guide's statement that ambiguous submissions are not resubmitted.
- "Preserve the returned `request_id`" is actionable. The request also carries it as `correlation_id` and `metadata.orpheus_request_id`, which an operator can use to find the child on the host side.

## P3 corrections

| # | Status | Notes |
| --- | --- | --- |
| 1 | Resolved | Separates `quarantined`, `unavailable_policies`, `unavailable_routes` (only routes whose bound policy is unavailable) and top-level failures. Names `invalid_config` only as an example, alongside specific deployment codes, `source_unavailable` for deployment YAML syntax, and `invalid_config` for duplicate keys. |
| 2 | Resolved | Says only the first failing check per candidate is reported, and to recheck after each fix. |
| 3 | Resolved | A `parent`/`systemone` preset selector makes every valid preset reachable, including newly added ones. |
| 4 | Resolved | Rule fields must be in `routing_fields` on every route bound to the policy. |
| 5 | Resolved | Explains the offline-validation blind spot and the runtime outcomes: dropped, or rejected when also listed in `required_fields`. |
| 6 | Resolved | Preset and tuple IDs are now included in the keep-secrets-out list. |
| 7 | Resolved | `systemone_client` is now an "argument/instance attribute"; `jev_client` stays "argument/property". |
| 8 | Resolved | "Through the subagent entrypoint" is removed, so the Jev claim no longer goes beyond the evidence. |
| 9 | Resolved | Names `allow_loopback_http: true` on the target and marks it as for local tests only. |
| 10 | Resolved | Names the three offline gaps and points to `orpheus_presets` capability reasons. Those reasons correspond to the preflight checks `unsupported_effort`, `unauthorized_tools` and `unverified_settings`. |

The corrections introduce no new inaccuracies against the supplied source. The README has no delta.

## Optional (non-blocking, outside the original findings)

There is one narrow window: if the SQLite update *after* a successful `lifecycle.launch` raises, the caller sees an error rather than `unknown`, and the row stays `starting`. The guide's phrase "a normal accepted spawn returns `state: running`" does not tell agents to treat other errors as safe to retry, so this does not block approval. It could be addressed later in the implementation rather than the docs.
