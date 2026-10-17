# Claude final review — Jev endpoint and live decision evidence

Requested claude-opus-5-5 high; reported ['claude-opus-5-5']; exit 0. Fresh no-tools source-only session. Final local verification: 113 tests and 57 subtests passed; wheel and source distribution builds passed. The two nonblocking operator-attribution wording suggestions below were applied after this review, recorded separately in its snapshot.

# Follow-up review: Jev endpoint binding and evidence provenance

**Verdict: APPROVE**

This is a source-only review. I ran nothing and verified no hashes. Files listed as unchanged keep the coverage from the prior review. I read every changed file in full.

## Prior blockers

**P2-1 (credential binding): resolved.** In `orpheus/deployment.py`, `validate_deployment` now rejects a `jev_endpoint` that differs from `DEFAULT_JEV_ENDPOINT` unless `jev_token_env` is also set.
- It still accepts a token-only legacy override.
- It still accepts an explicit original endpoint.
- Endpoint validation runs before the binding check. So an invalid endpoint still reports `invalid_jev_endpoint`, which the invalid-endpoint subtests rely on.
- Comparison is textual. Equivalent spellings of the default (trailing slash, `:443`, different case) also need an explicit token variable. That fails closed, so it's acceptable.
- `test_endpoint_requires_explicit_credential_binding` covers all three forms.

**P2-2 (evidence provenance): resolved.**
- `receipt.json` no longer contains `operator_metadata`, so its shape matches what the original probe could emit.
- The sidecar records the receipt SHA-256, both probe hashes, the task texts, and that module hashes weren't captured.
- The evidence README states that the exact module bytes from the past run aren't cryptographically established.
- No hashes were invented after the fact.

**Final-tree verification:** you report 113 tests / 57 subtests passing and a passing wheel+sdist build on the final candidate. I accept that as reported and have not checked it.

**Prior P3s:**
- P3-2 is resolved: the evidence README now says "synthetic … explicit domain/complexity cues".
- P3-3 is resolved: the top-level README now says resolver-only, synthetic task models, default Typesafe endpoint not tested live, and native effort still rejected.
- P3-6 is resolved: `isinstance(choice, str)` is checked before membership, and the `[]`, `{}`, `None`, `1` cases are tested.

## Remaining wording issue (non-blocking)

In `docs/evidence/jev/README.md`, two claims rest only on the operator's word but read as established facts:
- "The decision cases and API protocol were unchanged; no API rerun was performed…" No diff from `b29196a…` to `05811d…` is published.
- "The receipt hash proves the published sanitized receipt matches the retained original probe output." The hash only identifies the published bytes. Matching them to the original depends on the operator's retained copy, which isn't published.

They sit next to the operator sidecar, but the text doesn't say "per the operator". I suggest a one-phrase fix before merge, such as "The operator states that…" and "…matches, per the operator, the retained original output". This doesn't change the verdict.

## Already-acknowledged follow-ups

These are bounded follow-ups with no rerun or benchmark claim, and none block approval:
- **P3-4:** the endpoint validator still accepts some malformed values.
- **P3-5:** the JSON-decode path still keeps the response body on `__context__`.
- **P3-7:** the probe nits.
- There is no plugin-level test that an endpoint-only deployment fails registration. `validate_deployment` already covers this.

No material issues remain.
