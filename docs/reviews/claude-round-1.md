# Claude document review — round 1

Requested model: `claude-opus-5-5`. Reported model usage: ['claude-opus-5-5']. CLI exit: 0. Review uses supplied document snapshots without tools.

# Independent review: hermes-orpheus requirements and technical design

I only reviewed the four documents. I edited nothing, made no tool calls and ran no tests. This review covers whether the design documents fit together. It is not approval to implement.

## Overall assessment

The documents mostly agree with each other. They follow your selection policy by entrypoint everywhere:
- **Subagents:** the existing parent LLM may choose preset, model and effort.
- **Webhooks:** only rules or Jev choose, before the session starts, with no bootstrap LLM and no LLM fallback.

The documents also keep three things apart: what Hermes can do today (pinned `7e9eb8d`), what Orpheus proposes, and what release gates still need proof. The missing subagent effort field is clearly acknowledged as a host blocker, so I don't count it as a document defect.

What remains is one security and deduplication gap, plus several state-machine and schema decisions that are needed before anyone can build this. Details follow.

## Findings

### P1 — Webhook deduplication assumes the delivery ID is authenticated, but common signature schemes don't sign it
**Where:** design.md › Durable delivery and launch state; spec req 41; design › Webhook adapter (authentication paragraph).

The ledger's unique key is `(execution target, route scope, delivery ID)`. Some HMAC schemes sign only the request body and send the delivery ID in an unsigned header; GitHub's `X-Hub-Signature-256` with `X-GitHub-Delivery` is the standard example.

Anyone holding one captured signed body can resend it with new delivery IDs. Each copy:
- passes authentication;
- avoids the "same key, different digest" conflict check;
- starts a new top-level session, with paid Jev calls and provider calls.

The design says "a route without a stable authenticated delivery identity is incompatible with supported deduplicated delivery". But it never defines what makes a delivery ID authenticated for each `auth_profile`. It also doesn't say whether such a route is rejected at config time or accepted without deduplication. Under a strict reading, GitHub-style routes, which are the main reason to migrate Gormes, would be silently unsupported.

**Fix:**
- For each `auth_profile` type, declare whether the delivery ID is covered by the signature.
- If it isn't covered, require one of:
  - a secondary replay index keyed on `(route scope, canonical body digest)` that lasts for the replay window, or
  - a signed timestamp with a freshness check.
- Otherwise reject the route at config time and report it as `incompatible` in capability reporting.
- Define "canonical event digest": raw body bytes, or the normalized fields.
- Add a release-gate case: the same signed body arrives with N different delivery IDs, and at most one session starts.

### P2 — The `unknown` state has no way out, and nothing drives recovery
**Where:** design.md › Durable delivery state table; Subagent adapter (the `unknown` paragraph); spec reqs 28, 41, 45.

`unknown` only says "freeze automatic launch and expose reconciliation status". Several things are undefined:
- No transition leads out of it: no operator action and no automatic reconciliation.
- The acknowledgment is returned once the delivery is durably recorded, so selection and dispatch run asynchronously. The design never says what resumes stale `resolving` leases or `selected` rows after a crash: a startup sweep, a periodic reconciler, lease timeouts, and who owns them.
- `running` says to "poll supported public status surfaces", but no endpoint is named or marked as an open dependency. That leaves completion, failure and result retrieval for webhook sessions (req 45) without a source.

**Fix:**
- Specify a reconciler, covering:
  - its trigger: startup, plus a fixed interval;
  - the lease duration;
  - which states it may advance.
- Specify exits from `unknown`:
  - an operator "mark failed / mark abandoned" action, with an audit record;
  - after the idempotency gate passes, a lookup by the same idempotency key that resolves to `running`, a terminal state, or "not found within retention".
- Name the public run status and result surface. If it isn't verified yet, list it under "Open implementation decisions" as a dependency that gates req 45.

### P2 — Webhook status queries and cancellation have no caller identity or API surface
**Where:** design.md › Webhook adapter, last paragraph; spec reqs 27 and 45.

The design says "polling/status access requires the same route/owner authorization". But a webhook sender has no session credential, so the owner of a delivery is undefined. Cancellation also has no designed endpoint or authorization model. The design never says whether cancelling a `running` webhook session maps to a public API-server cancel operation, and no such operation is cited.

**Fix:**
- Define an operator-side credential for status and cancel, separate from the webhook signature secret.
- Name the cancel path, or explicitly report webhook cancellation as `unsupported` per entrypoint in capability reporting, as req 45 allows.

### P2 — Contradictory registry refresh semantics
**Where:** design.md › Registry revisions and capability reports.

Two rules conflict:
- "Compile each preset independently; other valid presets remain discoverable."
- "A failed refresh preserves the previous published snapshot; do not silently keep an invalid new definition under the same revision."

Take preset X: v1 was valid and v2 has been edited into something invalid. The rules don't say whether the new snapshot:
- (a) publishes X as unavailable with diagnostics, as req 4 implies, or
- (b) keeps the old snapshot so X v1 stays selectable.

Option (b) would keep serving a definition the operator has already replaced.

**Fix:**
- Define a "failed refresh" as source-level failure only: an I/O error, unparseable YAML, or a schema_version mismatch. In that case keep the previous snapshot.
- Handle per-preset invalidity by publishing a new snapshot in which that preset is quarantined. Its older revision must never stay selectable.
- Say whether policies that reference a quarantined preset become unavailable in the same snapshot.

### P2 — How payload fields become `event.*`, and their types, is undefined, so the config example can't be built
**Where:** design.md › Configuration model (`routing_fields`, `task_fields`) and Deterministic rules.

The rule evaluator's behavior depends on a "declared field type": `contains` means list membership or substring depending on that type, and a type mismatch is a validation error. Yet the schema has nowhere to declare types, and nothing defines how the raw payload maps to `event.kind` or `event.labels`.

A real `labels` field may be an array of objects rather than strings. The example config cannot be evaluated deterministically as written, which undercuts req 32's determinism and req 35's distinction between trusted and untrusted inputs. The example is also labelled "illustrative valid YAML", which overstates it.

**Fix:** add a per-route `event_schema` or extraction block. For each normalized field it should give:
- the source location: header, which is authenticated metadata, or a body JSON path, which is payload data;
- the declared type: string, string list, enum, number or bool;
- the maximum size;
- whether the field counts as trusted metadata or untrusted payload.

Also define how `task_fields` are combined into the run `input`, using a fixed, non-executing format. The design's no-templates rule leaves this unspecified today.

### P2 — How a subagent policy is chosen is undefined, which lets a parent bypass a configured rule/Jev policy
**Where:** design.md › Subagent adapter: spawn accepts a "policy ID". Spec reqs 14, 15 and 5.

Req 14 implies one subagent policy per configuration. The design instead allows several named policies and lets the parent pick one in `orpheus_spawn`. That has two consequences:
1. If an administrator configures both a `rules` policy and a `parent` policy, the parent can pick `parent` to avoid the rules policy. Req 15 forbids exactly that.
2. The design never says that `orpheus_spawn` rejects policies whose `entrypoint` is `webhook`. "Do not trust a payload's claimed entrypoint" covers only the webhook direction.

**Fix:** choose one of these:
- one subagent policy per parent profile or deployment, bound by the administrator; or
- a policy list scoped per preset, where the preset or the administrator decides, not the parent.

Separately, state that spawn rejects any policy whose `entrypoint` is not `subagent`. Add both cases to the Registry and policy gate.

### P2 — Policy-level `fallback` versus `no_match` is undefined
**Where:** design.md › Configuration model (`policies.*.fallback` and `field_resolver.no_match`); Jev section ("acyclic fallback graph").

The example sets both keys, but the schema never says:
- which failures go to the policy-level `fallback`: selector errors, field-resolution errors, validation failures, or all of them;
- whether fallback applies per stage (preset selector versus field resolver) or once per policy;
- how a fallback edge names its target. "Another ruleset or Jev" has no reference syntax.

Req 34 says fallback must disclose its identity and reason, so each edge needs a stable name.

**Fix:**
- Define `fallback` separately for each stage, as `preset_selector.on_error` and `field_resolver.on_error`, with its own list of error classes.
- Keep `no_match` limited to deterministic rule evaluation.
- Give fallback targets referenceable IDs.
- Check acyclicity and webhook eligibility (no `parent`, no LLM) at compile time and again at dispatch, as already stated.

### P3 — Smaller gaps

- **`compatible_settings` and discovered inventory** (design › Configuration model; spec reqs 6 and 16). The design doesn't say whether `compatible_settings` is mandatory. If a preset omits it, are all capability-valid combinations allowed? Jev field resolution and rule `settings:` both require named tuples. The design also doesn't explain how a discovery-generated model inventory (req 6) becomes tuples with stable IDs inside a preset revision. **Fix:**
  - require explicit tuples for the Jev and rule stages;
  - define a deterministic tuple-ID scheme for discovered inventory;
  - say whether parent proposals outside the tuples are rejected.
- **Effort on the subagent adapter while it is gated** (design › Decisions and boundaries). "Must reject presets requiring effort" doesn't say whether a `fixed` effort value counts. **Fix:** state that any effort declaration, fixed or enum, makes a preset incompatible on the subagent entrypoint until the gate passes. Leaving the field out means inheriting the parent's effort, and inherited effort alone doesn't satisfy req 11. Also note that the example's `interactive` policy is unusable for `analyst` on the reviewed host.
- **The `unknown` state on the subagent side.** Req 25 lists subagent states without `unknown`, while the design and req 28 use it. **Fix:** add `unknown` to req 25's list, or define how it maps.
- **Where the Jev projection is configured.** Jev's "permitted projection fields" sit on the policy, while `routing_fields` and `task_fields` sit on the route. **Fix:** pick one authoritative location, or say they intersect.
- **Empty-registry guidance** (req 3) is listed only as a test gate. Add a sentence on what `orpheus_presets` returns when no presets exist.

## Requirements coverage

All 46 requirements are mapped in the traceability table. These are the weak spots:

| Requirement | Gap |
|---|---|
| 3 | No discovery behavior for an empty registry (P3). |
| 15, 5 | Parent can choose the policy (P2). |
| 32, 35 | No event typing or extraction (P2). |
| 34 | Fallback semantics undefined (P2). |
| 41 | Delivery-ID authentication; no reconciliation exits (P1, P2). |
| 45 | No webhook status, result or cancel surface (P2). |

Requirements 11, 36, 39 and 40 depend on host capabilities the documents already acknowledge as blockers: the subagent effort field and proof that effort, first request and fallback are enforced. They are correctly marked as release gates, not defects.

I found no invented Hermes API. Interfaces Orpheus would add are labelled as proposals, and the pinned-source claims are kept separate from the unverified runtime behavior.

VERDICT: REQUEST_CHANGES
