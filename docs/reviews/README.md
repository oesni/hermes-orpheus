# Requirements and design review

Date: 2026-10-17. Reviewer: independent Claude CLI, requested and reported model `claude-opus-5-5`. Each round used a fresh invocation with no tools or persisted session and received complete requirements, design and feasibility snapshots. The review did not independently inspect upstream code or execute the plugin.

**Final verdict: APPROVE — design-document coherence only.** No remaining material findings. This is not implemented functionality, release approval, or live host/provider/Jev verification.

| Round | Verdict | Outcome |
|---|---|---|
| [1](claude-round-1.md) | REQUEST_CHANGES | Replay identity, recovery/control authority, registry refresh, extraction schema, policy binding and fallback definitions required correction. |
| [2](claude-round-2.md) | REQUEST_CHANGES | All first-round findings resolved; subagent typed inputs, tuple reachability, early cancellation, response reporting and result retention clarified. |
| [3](claude-round-3.md) | APPROVE | All second-round findings resolved; no remaining material findings. |

Exact reviewed file hashes are in [round 1 snapshot](claude-round-1-snapshot.json), [round 2 snapshot](claude-round-2-snapshot.json), and [final snapshot](claude-round-3-snapshot.json). Reports are preserved as returned. Those hashes describe the original reviewed documents. Later user-requested scope updates are separate changes and do not inherit the original document approval automatically.

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

Each numbered report has a sibling `implementation-round-N-snapshot.json` containing exact supplied-file hashes. The separate [CI review](implementation-ci.md) approved the workflow, ignore settings and compatibility verifier. Approvals cover source inspection only: no reviewer executed a real Hermes gateway, provider or Jev call. See [implementation limits](../implementation.md) for the current stock-only release.

## Core-unmodified release scope

The user subsequently requested only features supported without Hermes core changes. The companion patch/fixtures and patch tests were removed; native effort/fallback extension support was removed, native examples now select models only, and webhook model/effort selection remains. Reviews above are historical snapshots of the broader implementation; the scoped update is reviewed separately.

[Core-unmodified scope review](stock-only.md): Claude APPROVE, no P0/P1/P2. Minor wording/test-name corrections were applied afterward; optional early capability warnings remain future UX work (unsupported effort is already visible in discovery and rejected at launch). Full verification passed 92 tests plus 22 subtests and package builds. Removed compatibility references were checked in active source/config/docs; historical review reports retain their original text. The webhook deployment example contains no native effort override.

## Native directory installation and actual local review

[Initial review](local-hermes.md) requested a dependency-documentation correction and minor test/evidence improvements. [Final review](local-hermes-final.md) APPROVE: no material defects after those corrections. This covers the directory entrypoint, manifest, capture verifier, regression tests and documentation; the reviewer did not run the live model. Root separately executed and verified the actual local Hermes reviewer preset: see [live evidence](../evidence/local-hermes/README.md). Final local suite: 101 tests and 30 subtests passed, builds passed, public plugin doctor passed. The final verifier was rerun against the redacted export; its output matches the receipt exactly, and its SHA256 is recorded as operator metadata.

## Configurable Jev endpoint and live decisions

[Initial review](jev-live.md) requested explicit credential binding for custom endpoints and clearer evidence provenance. [Final review](jev-live-final.md) **APPROVE** after both corrections and a non-string choice guard. Unchanged files retain exact-hash coverage from the initial review; snapshots identify reviewed bytes. Two nonblocking operator-attribution wording suggestions were applied afterward. Full final verification: 113 tests and 57 subtests passed; wheel/source builds passed. The reviewer did not execute the [live Jev smoke test](../evidence/jev/README.md). Minor parser/probe hardening suggestions remain follow-ups; no routing-quality benchmark or native effort execution is claimed.

## Fixed-preset webhook integration

[Initial review](webhook-preset.md) requested evidence qualifications, an independent configured-instructions oracle, and optimized-Python refusal. A new live run on the hardened harness passed two real Hermes executions. [Correction review](webhook-preset-round-2.md) accepted those changes and found an overly broad expected-exception assertion in the corruption regression. [Final narrow review](webhook-preset-final.md) **APPROVE** after the assertion was restricted to the probe call. Unchanged runtime/harness coverage is inherited through exact source hashes. Full final suite: 120 tests and 57 subtests passed. Reviewers did not execute tests or live models. See [webhook evidence](../evidence/webhook-preset/README.md) for the exact recorded scope and operator observations.

## README cover and configuration authoring guide

[Initial review](cover-guide.md) requested corrections to tool inheritance, native input limits, credential routing and configuration guidance. [Second review](cover-guide-round-2.md) accepted those corrections and requested explicit unknown-launch handling. [Final narrow review](cover-guide-final.md) **APPROVE** after the remaining corrections; exact snapshots preserve prior full-contract coverage. Requested Claude Opus 5.5 with high effort, reported `claude-opus-5-5`; reviewers used no tools or live providers. Local verification passed 35 relative link targets, six example CLI validate/inspect commands, two context variants, and two guide YAML fragment applications. The cover matches the user-selected image byte for byte; visual inspection was performed separately by the coordinator. No runtime or package implementation changed.
