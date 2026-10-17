# Claude document review — round 2

Requested model: `claude-opus-5-5`. Reported model usage: ['claude-opus-5-5']. CLI exit: 0. Review uses supplied document snapshots without tools.

# Independent review of hermes-orpheus requirements and technical design (round 2)

I reviewed only the four document snapshots supplied in the request. I made no tool calls, edited nothing and ran no tests. This review covers whether the design documents fit together. It is not approval to implement.

The documents keep the confirmed policy that selection depends on the entrypoint:
- **Subagents:** the existing parent LLM may choose preset, model and effort.
- **Webhooks:** only rules or Jev choose, before the session starts, with no bootstrap LLM and no LLM fallback.

They also keep three things apart: what Hermes can do today at `7e9eb8d`, what Orpheus proposes, and the release gates. Subagent effort is clearly acknowledged as a host blocker; I don't count it as a document defect. I couldn't verify the cited host status, stop and `resolve-unknown` surfaces without tools, so I took them as cited.

## Round 1 findings: all resolved

| Round 1 finding | Status in this snapshot |
|---|---|
| P1: unsigned delivery ID lets one signed body start many sessions | **Resolved.** Each auth profile declares what its signature covers. A secondary index on the raw-body SHA-256 is reserved in the same transaction. Profiles with neither mechanism are rejected. Replay retention and rotation rules are stated, and there is a gate case for "N header IDs start at most one session". Spec req 41 is aligned. |
| P2: no exit from `unknown`, nothing drives recovery | **Resolved.** The reconciler runs at startup and every 10 s, with 60 s leases, renewal every 20 s and fencing generations. `starting` cannot be dispatched a second time. Exits are: confirmation through an authenticated read, attaching a verified host ID, or the `abandoned` disposition. No invented "mark failed" action. |
| P2: no caller identity or API for webhook status and cancel | **Resolved.** Operator endpoints use credentials scoped to the route's security scope. Stop is mapped to `stopping`, then polled until confirmed. |
| P2: contradictory registry refresh rules | **Resolved.** An invalid preset is quarantined in a new snapshot. A source-level failure freezes admissions. Policies that reference an unavailable preset become unavailable in the same snapshot. |
| P2: payload fields have no extraction or types | **Resolved.** `event_schema` declares JSON pointers, types, bounds and trust level. The format for building `input` from `task_fields` is fixed. |
| P2: parent can choose a policy to bypass rules | **Resolved.** One `subagent_policy` is bound per profile or deployment. A supplied policy ID or a webhook policy is rejected. Gate added. |
| P2: `fallback` versus `no_match` undefined | **Resolved.** `on_error` is per stage, with error classes, edge IDs and `resolver_nodes`. `no_match` is separate. The graph is compiled and checked again at dispatch. |
| P3: `compatible_settings` and discovered inventory | **Resolved.** Tuples are mandatory, IDs use a deterministic SHA-256, nothing is silently truncated, and proposals outside the tuples are rejected. |
| P3: effort on the gated subagent adapter | **Resolved.** Any effort declaration is rejected on subagents, and `analyst` is marked unavailable. |
| P3: `unknown` missing from req 25 | **Resolved.** |
| P3: where the Jev projection is configured | **Resolved.** The effective projection is the intersection of the policy, route and schema fields. |
| P3: empty-registry guidance | **Resolved.** |

## Remaining findings

### P2: Subagent rules and Jev have no defined inputs
**Where:** design.md › Subagent adapter and the Jev section ("administrator-approved subagent context fields"); spec reqs 14, 21, 32, 35; feasibility.md › Proposed subagent integration boundary, steps 2–3.

Spec reqs 14 and 21 allow a subagent policy to use rules or Jev and to "accept routing inputs and resolve the preset". The rule evaluator needs declared field types over allowlisted dotted paths. But only webhooks have a typed extraction schema (`event_schema`). Nothing defines:
- which spawn arguments become rule or Jev fields (task text? keys of the explicit context?);
- their types and size limits;
- the fact that a parent can never supply them as `verified_metadata`;
- whether undeclared context keys are rejected.

Without that, a subagent rules or Jev policy can't be built deterministically. Req 35's line between configured inputs and authoritative inputs also has nothing to enforce it. Separately, feasibility step 2 ("the parent chooses a preset") contradicts a subagent preset selector that uses rules or Jev.

**Fix:** pick one of these.
- **(a)** Add a per-policy `input_schema` for subagent policies. It would name spawn fields such as `task.text` and `context.<key>`, give each a type and bounds, force `trust: payload`, and reject undeclared keys at spawn. Then add rules and Jev with subagent inputs to the Registry and Deterministic-rules gates.
- **(b)** State that subagent rules and Jev selection are `unsupported` in the initial release, and report that in discovery.

Either way, make feasibility step 2 conditional on the bound policy.

### P3: Field rules can name tuples the selected preset doesn't define
**Where:** design.md › Deterministic rules and Configuration model.

Field rules name tuples (`settings: complex`) from the pinned preset's `compatible_settings`. If the preset selector can return several presets (rules or Jev), a tuple name may be missing from some of them. The compile-time check isn't stated.

**Fix:** require that every tuple name a field resolver references exists in every preset the selector can reach. As an alternative, allow a predicate on the selected preset. Fail at configuration time, not at dispatch.

### P3: Cancelling a webhook during `resolving` is undefined
**Where:** design.md › Durable delivery state table.

The table defines cancellation only from `selected` onward. The operator cancel endpoint can be called during `resolving`.

**Fix:** a fenced transition, `resolving → cancelled`. A late selector result must not move the request to `selected`.

### P3: How rejections and duplicates are reported isn't defined
**Where:** design.md › Durable delivery and Webhook adapter; spec req 45.

Req 45 needs rejected outcomes to be distinguishable. But auth and filter rejections happen before the ledger, so `GET /orpheus/requests/{id}` can never show them. The HTTP status codes are also unspecified for:
- a duplicate delivery;
- the same authenticated ID with a different body (a conflict);
- an incompatible route;
- an accepted delivery.

Senders retry on non-2xx responses, so the codes matter.

**Fix:**
- Define a bounded rejection audit record with no payload: route, reason class and time.
- Define the response code for each case. For example: duplicate returns 200 with the existing state; conflict returns 409; auth failure returns 401 or 403; accepted returns 202.

### P3: Results may expire before anyone retrieves them
**Where:** design.md › `RunRecord` ("partial/final result reference") and Webhook adapter ("Missing/expired output remains unavailable").

The design doesn't say whether Orpheus copies result bodies or only points at host output, which can expire. Reqs 26 and 45 need results to be retrievable.

**Fix:** decide whether Orpheus persists result bodies. If it does, define their size limits, redaction and retention, and say how that retention relates to the ledger and replay retention. If it doesn't, report expiry as `unavailable`.

### P3: The example YAML omits the auth profile schema it depends on
**Where:** design.md › Configuration model.

The example relies on `auth_profile: issue-source`, which must declare its signature coverage and choose either a signed event ID or the raw-body index. No schema for that is given. Migrating Gormes (a GitHub-style HMAC route) depends on it.

**Fix:** add an illustrative `auth_profiles` entry showing the coverage declaration and the dedup mechanism. Alternatively, label the example "valid only given profiles declared elsewhere".

## Requirements coverage

All 46 requirements now have design coverage that holds together. Two weak spots remain:
- **Reqs 14, 21, 32 and 35 on the subagent rules and Jev path** need the P2 decision above.
- **Req 45** needs the rejection and response-code detail above.

As before, reqs 11, 36, 39 and 40 depend on acknowledged host gates (subagent effort, plus proof of first-request effort and fallback enforcement). They are correctly listed as release gates. I found no invented Hermes API: proposed Orpheus interfaces are labelled as proposals.

VERDICT: REQUEST_CHANGES
