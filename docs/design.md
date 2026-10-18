# hermes-orpheus design

Status: design with user-selected core-unmodified release scope, 2026-10-17. This document describes an implementation plan, not an installed plugin. The [requirements](spec/subagent-presets.md) define desired behavior; [subagent feasibility](feasibility.md), [webhook feasibility](webhook-feasibility.md), and the [probe limitations](evidence/webhook-model-routing/README.md) distinguish verified source facts from remaining runtime proof. Hermes baseline: `7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357`.

## Decisions and boundaries

Use one plugin-owned preset registry and resolver, with two execution adapters. The existing parent LLM can supply preset and dynamic-field proposals for native subagents. A webhook endpoint runs rules/Jev before creating a top-level task session. It never creates a bootstrap agent or calls an LLM to select settings. No shared Hermes configuration is temporarily mutated.

All names, configuration keys, internal records, and Orpheus tools below are proposed Orpheus interfaces. Only explicitly identified Hermes surfaces are existing interfaces. The first implementation should support fixed and finite-enum fields. The schema reserves constrained `free` mode for the subagent parent-proposal path; until its validators are implemented, discovery reports it unsupported. This is a proposed rollout choice, not a change to the confirmed dynamic model/effort requirement.

The current release uses stock public APIs only. Native presets select model/provider and retain existing host reasoning configuration; every explicit native effort is rejected, including on an extended host. Per-launch fallback control, maximum turns, upstream patches and experimental middleware effort binding are excluded. Operators must verify host fallback is disabled. Webhook presets retain model/provider/effort selection through the public Run API. Effort-bearing examples below describe the webhook path; `examples/presets.yaml` provides the current native model-only configuration.

## Components and ownership

| Component | Responsibility |
|---|---|
| Registry compiler | Parse schema, reject duplicates/invalid definitions, compile rules, freeze candidate inventory and preset revisions. |
| Resolver | Enforce entrypoint policy, select preset, resolve fields, validate compatible combinations, produce immutable selection records. |
| Rule evaluator | Evaluate a restricted typed predicate tree; no Python, shell, templates with execution, or arbitrary expression evaluation. |
| Jev client | Send an allowlisted context projection and finite Choice candidates; validate responses, timeout, confidence and configured fallbacks. |
| Capability validator | Check provider/model/effort, authorization, tool bounds, adapter availability and runtime fallback constraints before launch. |
| Subagent adapter | Submit supported values to `ctx.subagent_lifecycle.launch`; normalize native handles, results and cancellation. |
| Webhook ingress | Authenticate/filter events, reserve durable delivery identity, invoke resolver, submit to authenticated public `/v1/runs`. |
| Run ledger | Persist immutable selections, state transitions, delivery identities and host handles; coordinate concurrent ingress. |
| Observation adapter | Attach actual available runtime observations and redact diagnostics; never infer effective settings from a request echo. |

The plugin registers discovery/spawn/status/cancel tools and an API-server platform handler. Exact registration signatures will follow the installed host's public plugin contract. Internal components may share immutable objects; they may not share mutable per-run selection state.

## Configuration model

The following is a webhook-only illustration of the original schema; the native model-only example is [examples/presets.yaml](../examples/presets.yaml). It is conditional on the referenced authentication profile and execution target being declared in administrator configuration elsewhere; it is not a standalone deployable configuration. The external `issue-source` auth profile must explicitly declare body-signature coverage, unsigned delivery headers and the raw-body replay index with indefinite tombstones when signed freshness is absent. Provider/model identifiers are operator inventory references, not a claim that an example provider is installed. `small` and `large` refer to concrete authorized provider/model pairs defined by the administrator. The registry must reject this configuration at deployment if those identifiers or effort combinations are unavailable.

```yaml
schema_version: 1
inventory:
  models:
    small:
      provider: authorized-provider
      model: configured-small-model
      efforts: [low, high]
    large:
      provider: authorized-provider
      model: configured-large-model
      efforts: [low, high]
presets:
  - id: analyst
    purpose: Analyze a supplied task and explain the evidence.
    guidance: Choose larger settings for complex analysis.
    fields:
      model:
        mode: enum
        candidates: [small, large]
      effort:
        mode: enum
        candidates: [low, high]
      instructions:
        mode: fixed
        value: Explain conclusions and identify uncertainty.
    compatible_settings:
      routine: {model: small, effort: low}
      complex: {model: large, effort: high}
policies:
  incoming:
    entrypoint: webhook
    preset_selector: {id: incoming-preset, kind: fixed, preset: analyst, on_error: []}
    field_resolver:
      id: incoming-fields
      kind: rules
      on_error: []
      rules:
        - id: complex-label
          priority: 10
          when: {field: event.labels, op: contains, value: complex}
          settings: complex
        - id: routine-kind
          priority: 20
          when: {field: event.kind, op: eq, value: routine}
          settings: routine
      no_match: {kind: error}
webhooks:
  - id: issue-analysis
    path: /orpheus/webhooks/issue-analysis
    policy: incoming
    auth_profile: issue-source
    execution_target: primary-api
    event_schema:
      event.kind: {source: body, pointer: /kind, type: string, max_length: 64, trust: payload}
      event.labels: {source: body, pointer: /labels, type: string_list, max_items: 32, max_length: 64, trust: payload}
      event.title: {source: body, pointer: /title, type: string, max_length: 256, trust: payload}
      event.description: {source: body, pointer: /description, type: string, max_length: 8192, trust: payload}
    routing_fields: [event.kind, event.labels]
    task_fields: [event.title, event.description]
    receipt: {kind: disabled}
```

`auth_profile` and `execution_target` are administrator-managed references. Their secret storage/API integration is a deployment detail to verify; these are not invented Hermes settings. Execution targets bind an authorized API origin, bearer credential reference, profile/principal, supported inventory and capability report. Neither request payloads nor parent proposals may change them. Omitted `allowed_toolsets` means native inheritance. Explicit empty sets are rejected on the reviewed host. For an optional toolset field, every configured candidate must be within the entrypoint's authorized scope.

All schemas reject unknown keys, duplicate mapping keys, type coercion and conflicting declarations. `fixed` requires exactly one typed `value`; `enum` requires nonempty unique candidates; future `free` requires an explicit type and validator. No implicit model/provider concatenation is allowed: an inventory model reference resolves to both. Discovery-generated inventory must be snapshotted; availability changes after selection cause validation failure rather than silent reselection.

`compatible_settings` is mandatory in the initial schema and names valid complete tuples. Every tuple must satisfy all constituent fixed/enum declarations and provider capabilities; every selectable tuple has a stable ID inside its preset revision. Parent proposals outside these tuples are rejected. Discovery-generated inventories require a configured deterministic tuple generator that enumerates capability-valid combinations after fixed/enum constraints; tuple IDs are `tuple_` plus the full SHA-256 of canonical JSON containing provider, model, effort and any other dynamic fields. Reject duplicate/colliding IDs; sort candidates by ID. Freeze generated tuples into the preset revision before selecting; Jev remains limited to 255 choices and never implicitly truncates. Parent proposals must resolve to a valid tuple too. A fixed field remains fixed even if a tuple, rule, Jev answer or parent proposes a different value. Role instructions and tools are fixed initially; the same typed schema can support finite dynamic alternatives later, only when the execution adapter can enforce them.

## Registry revisions and capability reports

Compile each preset independently. Duplicate IDs quarantine every conflicting definition; other valid presets remain discoverable. A routing policy referencing an unavailable preset is unavailable in that same snapshot, while unrelated policies remain valid. Publish a new registry snapshot atomically with invalid presets quarantined: replacing a valid definition with an invalid one never leaves its old revision selectable for new requests. A source-level failure (I/O, unparseable YAML, unsupported schema version) preserves the last snapshot for accepted requests and inspection, but freezes all new admissions from that source and reports stale-source diagnostics until a successful refresh. These source failures are distinct from per-preset validation errors.

A registry revision hashes canonical non-secret definitions, routing policies, inventory and compatibility metadata. Each preset also has a content revision. A request pins its registry snapshot at admission and stores that immutable selection material before launch. Existing requests retain old snapshots even if files are removed. An inability to retain the snapshot produces `stale_preset` before launch. Secret rotation changes credential references/versions separately without persisting secret values; it must not broaden authority.

Discovery exposes `compatible`, `unsupported`, or `unverified` per entrypoint and field, with reasons and tested host/provider identities. Configuration validity is separate from execution capability. A model name accepted by a schema is not evidence that its provider honors effort. Production launch requires all requested enforcement capabilities to be verified for that deployment; source-only feasibility remains `unverified`.

Capability reports include native lifecycle access, model/provider resolution, effort enforcement, tool restrictions, request fallback behavior, observation coverage and recovery/idempotency limits. Public feature detection plus integration evidence is required; version numbers alone do not enable a capability.

## Selection pipeline

1. Validate caller identity, entrypoint, task and bounded explicit context. Webhooks first complete ingress authentication and filtering.
2. Pin the registry snapshot and entrypoint policy. Do not trust a payload's claimed entrypoint.
3. Select one compatible preset using the policy's parent, fixed, rule or Jev selector.
4. Resolve dynamic fields with the configured field resolver. Fixed values always come from the pinned preset.
5. Validate the entire tuple, authorization, available provider and adapter capabilities. Recheck liveness before launch without changing the selected tuple.
6. Persist the selection record and launch intent. Only then call the execution adapter.

For subagent policies, `input_schema` declares every allowed `task.text` and `context.<key>` field using the same scalar/list/enum types and size bounds as webhook extraction. `task` maps exactly to `task.text`; the optional explicit `context` argument is a typed object whose declared keys map directly to `context.<key>`. All such fields are forced `trust: payload`; caller-provided `verified_metadata`, undeclared keys and unsupported nested objects are rejected. Required fields must exist; optional omissions stay missing, with no coercion/default inference. Trusted host routing metadata is unavailable in the initial schema. Rule and Jev routing see only these declared values; Jev additionally intersects `projection_fields`. If the bound selector is parent, a preset ID is required; if rule/Jev, a supplied preset ID is rejected and routing uses these inputs. Field proposals are likewise accepted only under a parent field resolver.

Parent selection and field resolution are distinct operations. A policy may allow a parent-selected preset but require rule/Jev field resolution; parent field proposals are then rejected rather than ignored. Parent mode consumes the existing agent's tool arguments and adds no separate selector LLM call. Webhook policies reject `parent`, `free`, and any fallback containing an LLM route at configuration time and again at dispatch.

### Deterministic rules

The initial predicate language supports `eq`, `in`, `contains`, `exists`, and `all`/`any`/`not` over allowlisted dotted field paths. `contains` means exact list membership or literal substring according to the declared field type; no regular-expression execution initially. Missing values make comparisons false; `exists` distinguishes missing from present null. Type mismatch is an input validation error, never truthy coercion. Bound predicate depth, input size and rule count.

Lower numeric priority wins. Priorities must be unique within a ruleset; configuration order does not break ties. First match returns a literal preset ID or a named compatible tuple, depending on the stage. Compilation computes every preset reachable through the preset selector and its fallback graph; every tuple name referenced by field rules, defaults or fallback fixed results must exist and be valid in every reachable preset. Missing tuple names make the policy unavailable before admission. Jev field candidates are built from the actually selected pinned preset. There is no rule chaining that mutates inputs. No-match defaults to error; an explicit fixed default or named Jev policy is allowed and recorded. Preset and field rules both use the same frozen context and policy revision.

Authenticated origin does not make arbitrary content authoritative. For example, `event.labels` may be permitted as routing data while carrying no authorization power. Principal/route allowlists are derived from verified ingress data and cannot be replaced by task text. Rule selection never grants tools or credentials.

### System One resolver

Use `kind: systemone` in preset selectors, field resolvers, and referenced resolver nodes.
The deprecated `kind: jev` alias is accepted and normalized in compiled policies.
Source snapshots and revision hashes retain the operator-supplied spelling.
The deployment keys `jev_endpoint` and `jev_token_env` and the configured model ID
remain unchanged; this name identifies the Choice API protocol rather than a model.

Jev uses TypeSafe's documented System One Choice API. Preset routing chooses a finite entrypoint-compatible preset ID; field resolution chooses a finite complete tuple ID. The tuple approach prevents independent model/effort questions from producing incompatible combinations. Opaque candidate IDs map back to the pinned registry, never to arbitrary response strings.

Effective Jev projection is the intersection of policy `projection_fields`, route `routing_fields` plus `task_fields` (or administrator-approved subagent context fields), and the typed extraction schema. Fields excluded by any layer are never sent, and required-but-excluded fields make that policy incompatible. At most 255 candidates are submitted per Choice. Exceeding that bound is a configuration error in the initial design; future explicit shortlisting must preserve an auditable candidate set. Do not truncate silently. A policy pins its Jev model and defines permitted projection fields, timeout, optional minimum confidence and bounded retry budget. No universal confidence threshold is assumed. Candidate guidance and task text remain data, not instructions to widen the candidate set.

Validate the selected ID, answer shape and confidence against the exact pending request. Missing credentials, authentication failure, rate limits, timeout, malformed/out-of-set answers and low confidence have separate error codes. Retries are restricted to selection, before launch, with an overall deadline. Fallback is stage-specific: each selector/resolver has a unique `id` and `on_error` array, default empty. Each entry is `{id: edge-id, errors: [timeout, rate_limited], target: resolver-id}`; IDs resolve to nodes in a policy-level `resolver_nodes` map of the same stage/output type. Allowed classes are `timeout`, `rate_limited`, `service_unavailable`, `invalid_response`, and `low_confidence`; an error may match only one edge. Credential/authentication/authorization errors, configuration errors, capability failure and final tuple validation never reroute. Rules alone use `no_match`: either `{kind: error}`, a literal fixed result, or `{kind: resolver, target: resolver-id}`. `no_match` is not an `on_error` class. Compile the entire stage graph for reference validity, unique IDs, acyclicity and entrypoint eligibility; repeat eligibility checks at dispatch. Every transition records its edge/node ID and cause; there is no policy-wide fallback. An explicitly configured graph may lead to a fixed result, another ruleset or Jev; every edge retains the originating entrypoint restriction and runs full validation. Record attempts and fallback reasons without payloads or secrets. Webhook execution never enters the parent-proposal path.

## Selection and execution records

`SelectionRecord` contains request ID, entrypoint, policy/registry/preset revisions, selector and field-resolver identities, matched rule or chosen tuple, candidate-set hash, typed requested and resolved settings, fallback attempts, and timestamps. Store only the minimum context needed for replay/audit under configured retention. Secrets and full parent transcripts are excluded. An explanation is optional and must come from an actual source, not generated post hoc as apparent evidence.

`RunRecord` adds launch intent, host run/session identifiers when known, lifecycle state, launch-accepted settings, observed effective values with observation source, partial/final result reference, cancellation state and structured errors. `requested`, `resolved`, `launch_accepted`, and `observed` are separate objects. A missing observation is null/unverified. Host echoes do not count as effective provider-request observations.

Provider fallback differs from selector fallback. The adapter must either demonstrate that fallback is disabled through supported administrator configuration, or validate and enforce every possible fallback tuple within the preset's constraints. If fallback could escape those constraints or silently discard effort, reject the target as incompatible. Observing a violation after a call does not satisfy prevention. Do not claim a per-request fallback-disable parameter exists without verifying it. Auxiliary calls such as compression are reported separately from task execution and must not accidentally receive another run's settings.

## Subagent adapter and parent tools

Proposed tools are `orpheus_presets`, `orpheus_spawn`, `orpheus_status`, and `orpheus_cancel`. Discovery reports policies, dynamic fields, constraints and capability reasons. Discovery returns an empty collection plus “Configure at least one compatible preset before spawning” guidance when none exist. The administrator binds exactly one `subagent_policy` per parent profile/deployment; callers cannot select or override it. Spawn accepts a nonempty task, optional explicit context, and parent preset/proposals only where that bound policy allows them. A supplied policy ID or webhook policy is rejected, as are proposals bypassing bound rule/Jev resolution. Returns an Orpheus request ID, selection record and native run ID when available. Status returns native execution state and available results; unsupported recovery is explicit. Tool names are not present in Hermes today.

Map the final model/provider and permitted toolsets to the public lifecycle request. Compose role instructions and task context without claiming a new Hermes lifecycle role or removing inherited rules. The child retains Hermes's separate conversation, memory/tool restrictions and skill behavior. Do not copy parent transcript or memory wholesale. The adapter maintains native ownership: one parent cannot inspect or cancel another parent's run through a guessed ID.

Reasoning effort is excluded from the native adapter in this release. The following alternatives are future research only, not implementation tasks: a future upstream field may support it. Public `subagent_start` plus `llm_request` middleware is an experimental alternative only: it must prove supported identity binding for identical simultaneous tasks, first-request ordering, provider-specific payload semantics, isolation, fallback handling and fail-closed behavior. Matching goal text is inadequate, and middleware's documented fail-open errors cannot be treated as enforcement. No private object mutation, global configuration swap or monkey patch is accepted.

The plugin owns resolving and starting states; native lifecycle supplies subsequent status/result/wait/cancel behavior. Serialize cancellation against the launch decision. Acknowledged prelaunch cancellation prevents adapter invocation; after submission, cancellation remains pending until the native outcome is known. Completion may win. A timeout without confirmed rejection is `unknown`, not failure permitting automatic respawn. Restart recovery is exposed only where native public handles can actually be reconciled.

Per-preset maximum turns, cwd, per-tool blocking and execution timeout are not initial supported fields. A wait timeout is not a run deadline. Unknown/unsupported values fail before launch rather than being silently ignored.

## Webhook adapter

Mount `/orpheus/webhooks/{route}` via the public `ctx.register_platform_handler("api_server", factory)` surface. Use asynchronous public HTTP to the administrator-bound authenticated `/v1/runs`; do not call private adapter methods or block the event loop while calling the same server. This is a new endpoint requiring explicit ingress configuration, not a change to existing native `/webhooks/...` behavior.

Authenticate the raw bounded request before parsing/selecting as required by its configured signature protocol. Each auth-profile type explicitly declares which bytes/headers and identity fields its signature covers; unsigned delivery-ID headers are diagnostic only. Admission requires either a unique body-bound/signed event identity, or a secondary raw-body replay index described below. A signed freshness timestamp alone does not deduplicate repeated submissions inside its freshness window. Apply timestamp/replay limits where supported, route/principal authorization, event filters and delivery identity checks before Jev. Arbitrary plugin routes do not inherit the API handlers' own authentication. Typed extraction uses literal RFC 6901 JSON pointers into a decoded body object, or named headers verified by the auth profile; no executable expressions, wildcards or coercion. Each field declares type (string, string_list, number, boolean or finite enum), size bounds, required/optional status (required by default), and `trust` (payload or verified_metadata). Missing required fields, type mismatch and size overflow reject admission. `verified_metadata` is allowed only for headers/values actually bound by the auth protocol; declaring it does not create trust. Array-of-object extraction is unsupported initially: route authors must select a supported normalized source or add a separately reviewed deterministic extractor. `task_fields` are formatted in configured order as `field-name: JSON-encoded-value` lines joined by LF; JSON escaping prevents payload newlines from changing field boundaries. Absent optional fields are omitted. This exact bounded text is run `input`, with no executable templates. Validate allowed content type, size and normalized event fields; do not let event URLs select an outbound API destination. API credentials stay server-side; TLS/origin and redirect policy are administrator-controlled.

Existing native receipt hooks remain untouched. A custom route must explicitly configure an equivalent adapter or declare receipts disabled as in the example. Receipt calls follow authentication/filtering and durable delivery reservation, occur before dispatch when configured, and are best-effort. Store confirmed, unconfirmed or skipped receipt state; overwrite attacker-provided receipt metadata. An ambiguous receipt is not retried automatically and never proves work completed. Migrating Gormes's route requires preserving its existing authorization and receipt semantics as a separate deployment acceptance check.

A fresh API submission supplies `input`, selected `model`, `provider`, and `model_options.reasoning_effort`; preset instructions use the documented `instructions` path, which layers on the core system prompt; integration tests must confirm inherited safety/project rules remain intact. Explicitly omit `session_id`, `previous_response_id`, caller history and reuse-affinity `X-Hermes-Session-Key`. Body/header allowlists prevent event data from restoring those fields. The selected execution target fixes the profile/principal; this design does not invent a profile body parameter. Reject route aliases or validate their exact resolved mapping before launch. Response model echoes are not effective-model proof.

Top-level toolsets follow API-server/profile configuration in the reviewed path. No per-request toolset override has been established. A preset requesting narrower tools must be rejected unless a supported target configuration enforces that exact restriction; do not represent a prompt instruction as a tool permission boundary. Memory and skills follow the selected target profile's normal top-level behavior, not subagent-only skipping. Resume/migration is outside this endpoint: it accepts only new logical sessions.

### Durable delivery and launch state

Use a plugin-owned transactional SQLite ledger initially, with unique identity `(stable authenticated route security scope, authenticated event ID)` when the event ID is signature-bound. The route security scope survives target, policy, secret-version and display-name changes; pin the execution target at first reservation, never include a mutable target in dedup identity. A duplicate authenticated ID with a different raw-body SHA-256 digest is a conflict. For protocols with unsigned delivery IDs (including body-signature-only protocols), atomically reserve a secondary unique index `(stable route security scope, SHA-256 of exact authenticated raw body bytes)` in the same transaction as the delivery record; all header-ID variants of those bytes resolve to that one logical record. No normalized/re-serialized JSON digest substitutes for these raw bytes. This intentionally collapses distinct legitimate events with identical bodies unless the source supplies a signed unique event identity; report that tradeoff at route configuration. Auth profiles without either mechanism are incompatible and rejected before activation. Replay indices/tombstones must persist indefinitely when no authenticated freshness bound exists. Where signed event time permits expiry, retain the index for the full accepted freshness window plus clock-skew allowance and reject expired events before identity lookup. Timestamp checks never replace the index. Rotation of secrets or execution targets cannot reset replay scope; deleting replay tombstones requires disabling admission of events still replayable under that scope. Multi-process workers must share the same ledger; multi-host ingress requires a shared transactional backend and is outside the initial deployment.

Persist these states and transition using compare-and-swap transactions:

| State | Meaning and permitted next action |
|---|---|
| `resolving` | Delivery reserved and snapshot retained. One leased owner may perform bounded selection. |
| `selected` | Complete immutable selection saved; no API call has been attempted. Cancellation can prevent launch. |
| `starting` | Exact body, target/principal, body digest and idempotency key persisted before network submission. Only one dispatcher may submit. |
| `running` | Host acceptance/identity known; poll supported public status surfaces. |
| `completed` / `failed` / `cancelled` | Confirmed outcome; keep partial result when available. Terminal states never initiate another launch. |
| `unknown` | Submission or post-restart outcome cannot be established. Freeze new launch; reconciliation may establish running/terminal state. Administrative abandonment is a separate disposition, not an execution outcome. |

Authentication/filter rejection occurs before the durable accepted-delivery lifecycle and is reported separately. Use 401 for missing/invalid authentication, 403 for authenticated authorization denial, 400 for malformed/type-invalid input, 413 for size limits, and 200 with `outcome=rejected, reason=filtered` for valid filtered events. An unavailable/incompatible route returns 503 with `outcome=rejected, reason=route_unavailable`; an unknown route returns 404. First durable acceptance returns 202 with request ID/state; a same-identity/same-body duplicate returns 200 with existing ID/state (including failed or unknown); identity/body conflict returns 409 without disclosing the existing record to an unauthorized caller. Status responses expose details only under operator authorization. Record pre-admission rejections separately in a local bounded audit ring (maximum 10,000 records, seven days), containing route security scope when known, reason class, timestamp and a random audit ID, never payload, signature, secret, raw headers or unverified claimed identity. Public errors reveal only coarse classes; operator audit access is credential-scoped. Retention of rejection audit does not govern accepted-delivery replay tombstones. Selection errors transition to failed with `phase=selection`; a confirmed launch rejection is failed with `phase=launch`. Neither is task completion. Retries of a failed delivery expose its existing outcome; deliberate new execution requires a new logical request explicitly requested by the operator.

Cancellation during `resolving` performs a fenced compare-and-swap to `cancelled` and revokes the lease; late selector responses cannot commit `selected` or start work. External selector cancellation is best-effort, but cancellation acknowledgment guarantees no task launch.

A reconciler runs at startup and every 10 seconds, using 60-second leases renewed every 20 seconds and monotonic fencing generations on all ledger transitions. It resumes stale `resolving` from its pinned snapshot, schedules owned `selected` rows, polls `running`, and reconciles `starting`/`unknown` without ordinary resubmission. A stale worker may finish an external selector call but cannot commit or cross the launch CAS with an expired generation. The committed `starting` state records the one dispatch generation: lease expiry never authorizes a second dispatcher. Later reconciliation replay is a separate idempotency-gated action. HTTP deadlines are bounded below the lease duration; an expired dispatcher cannot be assumed stopped externally. Unknown with a known host ID uses authenticated read-only status; confirmed host running/terminal observations may advance state. Unknown without an ID remains frozen unless verified native idempotency replay recovers the original ID. Not-found/expired/forbidden are not evidence of no prior execution and cannot cause a fresh run. Operators may attach a verified original host ID for audited reconciliation or mark the administrative disposition `abandoned`; execution remains `unknown` and dedup tombstones remain. No “mark failed” action invents a terminal host outcome.

Duplicate ingress reads the existing record and never reselects, even after registry changes. Stale resolving leases may be recovered against the exact persisted snapshot; lost selection responses may repeat a selector call but cannot launch twice. A crash after `selected` but before `starting` is safe to dispatch once under ownership. A crash after `starting` is ambiguous regardless of whether bytes were sent; do not infer no launch from a missing response. Cancellation of `starting`/`unknown` cannot be acknowledged as final until reconciliation proves no running work or confirms cancellation.

The pinned `/v1/runs` implementation has `Idempotency-Key` validation, lookup and reservation. Use a stable opaque ASCII key derived from the durable delivery record and store the exact submitted request. The pinned endpoint contract and store use a 24-hour retention window after status updates; scope includes authenticated profile/credential and the fingerprint includes the canonical body and session-affinity header. Credential rotation changes scope: retain non-secret scope identity and never replay under changed credentials as if deduplication still applied. Native replay may reconcile a lost acceptance using the same key, body and principal **only after** tests establish fingerprint semantics, durable retention, ownership and restart behavior for the deployed host. Until those guarantees are verified, `unknown` remains blocked and no network resubmission is attempted. Never retry under a new key or after retention expiry as if it were safe. Orpheus ledger retention must cover the admitted delivery replay window; expiry policy must reject stale replays or preserve dedup tombstones rather than silently treating them as new. This promises non-duplication under its stated deployment contract, not generic exactly-once execution across arbitrary failures.

The endpoint returns a bounded acknowledgment with Orpheus request ID and current state after durable acceptance, not after task completion. Proposed operator endpoints are `GET /orpheus/requests/{id}`, `POST /orpheus/requests/{id}/cancel` and `POST /orpheus/requests/{id}/reconcile`. They require administrator-issued operator credentials scoped to stable route security scopes, separate from webhook signature secrets and host API credentials; a webhook request ID is not an access token. Operator actions are audited. The webhook sender does not implicitly acquire operator access. The adapter uses the authenticated public `GET /v1/runs/{run_id}` for status/output and optional `GET /v1/runs/{run_id}/events`, and `POST /v1/runs/{run_id}/stop` for cancellation. These paths appear in the pinned API-server documentation and source; actual ownership/restart/retention behavior remains a live gate. Stop acknowledgment is `stopping`, not cancelled; poll until confirmed native cancellation or completion. Preserve native `interrupted` as failed with `phase=execution` and `native_status=interrupted`, and native `unknown` as unknown. Final `runtime` reports the final provider/model pair, not every request or effective effort. Missing/expired output remains unavailable. Native `resolve-unknown` acknowledges a host owner epoch and is not proof of no side effects; initial Orpheus reconciliation never invokes it automatically. Orpheus copies observed partial/final output into its protected ledger/result storage rather than relying solely on a host reference. Keep up to 256 KiB UTF-8 output per run (prefix at a valid character boundary), set `truncated=true` and observed byte count when larger, and retain it seven days after terminal observation. Apply configured secret-pattern redaction before storage and restrict access to the run owner/operator; redaction is not a guarantee that arbitrary sensitive task content is recognized. Store the source/native status and acquisition time. If host output expires before observation, report `result_availability=unavailable`; after local retention expiry report `expired`, never an empty successful result. Keep selection/status and replay tombstones for their separate required retention even when output is deleted. Status/retrieval never launches or reruns work to recreate missing output. The same bounded result contract applies to native-child results when observed. Completed results are retained for authenticated retrieval initially; external result posting is optional and must use a separately configured delivery adapter with its own retry/dedup contract. Receipt/result delivery failures do not change an agent's actual task outcome.

## Validation and release gates

| Gate | Required evidence before declaring supported |
|---|---|
| Registry and policy | Duplicate/invalid/empty registries; unknown keys; fixed override rejection; enum tuple mismatch; revision changes during selection; webhook cannot enter parent/free/fallback LLM paths; parent cannot choose policy or bypass bound rule/Jev fields; source refresh failure freezes admissions and invalid updated presets are quarantined. |
| Deterministic rules | Priority uniqueness, missing/null/type cases, no-match/default, bounded predicates, identical inputs/snapshot yield identical outcomes; typed subagent rule/Jev context, unknown keys, trust spoofing, missing fields and cross-preset tuple references. |
| Jev | Stubbed malformed/low-confidence/timeout/429/auth responses; finite candidates and projection audits; no secret/transcript disclosure; live account smoke test separately authorized for deployment. |
| Native child | Concurrent identical tasks with different models; explicit effort rejected, stock request shape and parent defaults checked; ownership, cancellation races, partial failures and restart limitations. |
| Webhook session | Real authenticated HTTP → plugin endpoint → public run API → fresh session → first provider request; cross-provider choice and effective effort; no selector LLM request. |
| Enforcement | Invalid effort, unsupported tools, aliases, model fallback and unavailable credentials fail before execution; provider request traces demonstrate actual settings. |
| Delivery durability | Same signed body with N unsigned header IDs starts at most one session; replay across freshness/retention/credential/target changes; parallel duplicates, different-body conflict, crash at every ledger boundary, lost acceptance, native idempotency replay/expiry/principal behavior, restart and cancellation ambiguity. |
| Compatibility | Profile memory/skills and inherited rules preserved; existing native routes/receipt hooks unchanged; two simultaneous top-level sessions and children remain isolated. |

The existing evidence bundle supplies source inspection and extracted/stub probes only. It does not satisfy these live gates. Keep test artifacts associated with adapter/host/provider versions and redact secrets. Native effort is deferred by the current scope rather than a release dependency; webhook first-request effort, fallback enforcement and durable replay remain deployment proof obligations.

## Requirements traceability

| Requirements | Design coverage |
|---|---|
| 1–4 | Shared registry, discovery and invalid-definition isolation. |
| 5–17 | Entrypoint policy, fixed/enum/free gates, complete tuples and capability validation. Current native scope omits effort; webhook effort remains supported. |
| 18–20 | Context projection, immutable selection records and explicit errors/fallback. |
| 21–24 | Parent tools, native child adapter, instructions and tool boundaries. |
| 25–31 | Run state, native lifecycle, cancellation, ambiguity, concurrency and revision pinning. |
| 32–35 | Typed deterministic rules, Jev policies and trusted routing boundaries. |
| 36–40 | Custom webhook admission and selected settings before first task request. |
| 41–45 | Durable delivery identity, new-session boundary, profile semantics and status reconciliation. |
| 46 | Capability reporting and explicit distinction between proposed behavior and verified execution. |

Open implementation decisions are the exact host registration signatures, deployable secret references, provider compatibility inventory, native idempotency retention contract, and live provider compatibility. Native effort adapters are outside current scope. They must be resolved by bounded integration experiments before claiming the complete requirement set is ready for production.
