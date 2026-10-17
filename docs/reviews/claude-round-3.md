# Claude document review — round 3

Requested model: `claude-opus-5-5`. Reported model usage: ['claude-opus-5-5']. CLI exit: 0. Review uses supplied document snapshots without tools.

# Independent review of hermes-orpheus requirements and design: round 3

I reviewed the four document snapshots you supplied. I made no tool calls, edited nothing and ran no tests. This verdict covers whether the design documents are coherent. It is not approval to implement.

The documents follow your entrypoint policy:
- **Subagents:** the existing parent LLM may choose the preset, model and effort, or the administrator can bind a rule/Jev policy instead.
- **Webhooks:** only rules or Jev choose, before the session starts. There is no bootstrap LLM and no LLM fallback, and configuration time and dispatch both enforce this.

The documents also keep three things separate: what the host can do today at `7e9eb8d`, what Orpheus proposes, and the live release gates. Subagent effort is still an acknowledged host blocker. I don't count it as a document defect.

## Round 2 findings: all resolved

| Round 2 finding | Status in this snapshot |
|---|---|
| P2: subagent rules and Jev had no defined inputs | **Resolved.** A subagent policy now declares an `input_schema`. It maps `task` to `task.text` and the declared keys to `context.<key>`, with types and size limits. Every field is forced to `trust: payload`. Caller-supplied `verified_metadata`, undeclared keys and nested objects are rejected, and missing fields are not filled with defaults. Under a rule/Jev selector, a supplied preset ID is rejected. Field proposals are accepted only under a parent field resolver. A Deterministic-rules gate covers spoofing, unknown keys and missing fields. Feasibility step 2 now depends on the bound policy. |
| P3: field rules could name tuples a selected preset lacks | **Resolved.** At compile time the design works out every preset the selector and its fallback graph can reach. Every tuple name must exist in all of them, or the policy is unavailable before any request is admitted. Jev builds its field candidates from the preset actually selected. |
| P3: cancelling during `resolving` | **Resolved.** Cancellation is a fenced swap from `resolving` to `cancelled` that also revokes the lease. A late selector result cannot reach `selected`, and acknowledging the cancel guarantees no launch. |
| P3: reporting rejections and duplicates | **Resolved.** Each case now has an HTTP status: 401, 403, 400, 413, 200 for filtered events, 503 for an unavailable route, 404 for an unknown route, 202 for first acceptance, 200 for a duplicate and 409 for a conflict. A bounded audit log records rejections without payloads (10,000 records, seven days) and is separate from the retention of replay records. Selection failures and launch failures are distinguished by phase. |
| P3: results could expire before retrieval | **Resolved.** Orpheus copies observed output into its own storage: at most 256 KiB, truncation flagged, kept seven days, redacted, and readable only by the run owner or an operator. Output the host let expire is reported as `unavailable`; output Orpheus deleted is reported as `expired`, never as an empty success. Retrieval never re-runs work. |
| P3: example config relied on an undeclared auth profile | **Resolved.** The example is now labelled as valid only when the referenced `issue-source` profile and execution target are declared elsewhere. It also lists what that profile must declare: which bytes the signature covers, the unsigned header IDs, and the raw-body replay index with permanent tombstones when no signed timestamp exists. |

## Remaining material findings

None.

These three clarifications are optional and don't affect coherence:
- **Jev projection wording (Jev section).** "administrator-approved subagent context fields" could say "the policy's `input_schema` fields". That would make the projection intersection match the new schema exactly.
- **Where `stopping` lives (state table and `RunRecord`).** The stop acknowledgment `stopping` is not a ledger state. It appears to belong to `RunRecord`'s cancellation state. One sentence saying so would stop implementers adding it as an extra lifecycle state.
- **Replay-index growth (Durable delivery).** Routes without a signed timestamp keep their replay index forever. You could state what happens when storage runs low, for example freezing admission with `route_unavailable` rather than dropping tombstones. The existing rule (tombstones may be deleted only after admission is disabled) already prevents unsafe deletion, so this is about running the system, not a contradiction.

## Requirements coverage

All 46 requirements have consistent design coverage:
- **Reqs 14, 21, 32 and 35 on the subagent path** are now buildable through `input_schema`.
- **Req 45** is covered by the defined status codes and the audit log.

Reqs 11, 36, 39 and 40 still depend on gates that have to be proved on the host:
- effort for subagents;
- effort on the webhook's first provider request;
- enforcing provider fallback;
- native idempotency retention.

These are listed correctly as release gates, not claimed as working. I found no invented Hermes API. The Orpheus tools, endpoints, configuration keys and records are all labelled as proposals. The host surfaces cited (`subagent_lifecycle.launch`, `register_platform_handler`, `/v1/runs` with its status/events/stop endpoints, and `Idempotency-Key`) are tied to the pinned revision. I took them as cited, since I couldn't check them without tools.

This approval covers design-document coherence only. It does not approve implementation or a release: no live plugin, provider, Jev or webhook integration test has been run, and the subagent effort gate is still open.

VERDICT: APPROVE
