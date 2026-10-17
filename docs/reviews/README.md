# Requirements and design review

Date: 2026-10-17. Reviewer: independent Claude CLI, requested and reported model `claude-opus-5-5`. Each round used a fresh invocation with no tools or persisted session and received complete requirements, design and feasibility snapshots. The review did not independently inspect upstream code or execute the plugin.

**Final verdict: APPROVE — design-document coherence only.** No remaining material findings. This is not implemented functionality, release approval, or live host/provider/Jev verification.

| Round | Verdict | Outcome |
|---|---|---|
| [1](claude-round-1.md) | REQUEST_CHANGES | Replay identity, recovery/control authority, registry refresh, extraction schema, policy binding and fallback definitions required correction. |
| [2](claude-round-2.md) | REQUEST_CHANGES | All first-round findings resolved; subagent typed inputs, tuple reachability, early cancellation, response reporting and result retention clarified. |
| [3](claude-round-3.md) | APPROVE | All second-round findings resolved; no remaining material findings. |

Exact reviewed file hashes are in [round 1 snapshot](claude-round-1-snapshot.json), [round 2 snapshot](claude-round-2-snapshot.json), and [final snapshot](claude-round-3-snapshot.json). Reports are preserved as returned. The four final reviewed documents remain byte-identical to the round-3 snapshot.

The reviewer suggested three optional editorial/operational clarifications: refer to the subagent input schema explicitly in Jev projection wording, identify `stopping` as cancellation state, and describe storage-pressure admission handling for permanent replay tombstones. These are recorded without changing the approved snapshot.

Remaining implementation gates are native subagent effort enforcement, actual first-request webhook settings, provider fallback constraints, and native idempotency/restart behavior. See the design's release-gate table.

## Implementation review

The runtime implementation was reviewed separately through fresh Claude CLI invocations, requested and reported model `claude-opus-5-5`. Review packets included first-party implementation/tests, examples, packaging, the companion patch and verifier, requirements, and implementation limitations. Vendor fixtures were excluded from the source-review packet and covered by pinned-hash verification and patch tests instead. The initial 360-second attempt timed out without a verdict; no approval is attributed to it.

| Round | Verdict | Outcome |
|---|---|---|
| [1](implementation-round-1.md) | REQUEST_CHANGES | Launch/observation lifecycle, strict configuration, permitted routing inputs, retention and privacy corrections. |
| [2](implementation-round-2.md) | REQUEST_CHANGES | Missing-host recovery, cross-file validation, unknown/abandoned retention corrections. |
| [3](implementation-round-3.md) | APPROVE with P3 findings | Permanent-failure polling, quarantine isolation and diagnostic corrections requested and subsequently implemented. |
| [4](implementation-round-4.md) | APPROVE with one P3 finding | Earlier findings resolved; rare acceptance-publication failure recovery corrected in round 5. |
| [5 — final delta](implementation-round-5.md) | APPROVE, no delta findings | Remaining P3 resolved; four changed files reviewed in full, all other reviewed files matched round 4 by SHA256. |

**Final implementation source verdict: APPROVE, with no unresolved review findings.** Integrated local verification: 98 tests and 21 subtests passed, pinned patch verification passed, and wheel/source builds passed. This combines the complete round-4 source review with the round-5 delta review; it is not a live deployment approval.

Each numbered report has a sibling `implementation-round-N-snapshot.json` containing exact supplied-file hashes. The separate [CI review](implementation-ci.md) approved the workflow, ignore settings and compatibility verifier. Approvals cover source inspection only: no reviewer executed a real Hermes gateway, provider or Jev call. See [implementation limits](../implementation.md) and [compatibility patch](../../compat/README.md).
