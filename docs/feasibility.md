# hermes-orpheus feasibility assessment

Date: 2026-10-17 (Asia/Seoul). Status: source/documentation assessment plus isolated webhook routing probes; no installed plugin, live API experiment, or Gormes deployment performed.

## Verdict

**Subagent presets and model selection are feasible as a standalone plugin; subagent dynamic effort has an unproven public-hook/middleware approach, blocked pending reliable binding and enforcement.** Preset storage, discovery, parent-agent selection, parent-proposed or rule/System One dynamic resolution, and per-child model/provider selection fit existing extension surfaces. The direct lifecycle request has no effort field. A public middleware adapter is a plausible alternative to an upstream extension, with additional correctness obligations below.

Optional per-preset iteration limits need another public launch field. Do not interpret the two launch gaps as a reason to build a new agent runtime or to silently discard selected values.

**Source inspection indicates a separate plugin-only route for webhook sessions:** register an Orpheus endpoint on the API-server platform, resolve preset/model/effort using rules or Jev, and submit a new run through authenticated `POST /v1/runs`. That public API accepts model/provider and reasoning options. This requires a custom endpoint; the existing native webhook dispatch has no equivalent public construction override. See [webhook feasibility and verification](webhook-feasibility.md).

## Evidence baseline and limits

Hermes upstream `main` was resolved with `git ls-remote` to **`7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357`**. Source statements below refer to that revision. Public documentation can move independently of source; pinned implementation is the authority for this assessment. Gormes's installed revision and enabled providers have not been inspected.

The user-created [repository](https://github.com/oesni/hermes-orpheus) was empty when cloned. These documents are a proposal, not evidence of implemented functionality or upstream approval.

## Subagent requirement mapping

“Supported” below means documented in the pinned source, not exercised in a live runtime.

| Requirement | Verdict | Basis / remaining work |
|---|---|---|
| Multiple presets available to the same parent | Plugin-only | Store definitions in plugin-owned configuration/data; register discovery and launch tools. No profile switch required. |
| Agent chooses a preset appropriate to a task | Plugin-only | Expose descriptions and criteria; parent calls the launch tool with the chosen identifier. Rules/Jev routing may be configured instead. |
| Fixed values | Plugin-only | Plugin validates and freezes settings before launch; caller proposals cannot override them. |
| Dynamic enum fields | Plugin-only selection | Parent proposals or System One Choice can choose candidates. Runtime support still controls what can be applied. |
| Dynamic free-form fields | Conditional | LLM can propose values; plugin validates type, policy, availability, and combinations. Jev does not generate arbitrary strings. |
| Per-child model/provider | Public API supported | `SubagentLaunchRequest.model` and `.provider`; provider must be configured and resolvable. |
| Per-child reasoning effort | **Direct launch API gap; unproven middleware path** | Request has no effort field. Public hooks/middleware may bind and rewrite child requests; provider-specific and concurrency behavior needs a proof of concept. |
| Per-child maximum iterations (optional) | **Public API gap** | Request has no iteration field. Lifecycle launch passes `DEFAULT_MAX_ITERATIONS` (250) directly in this revision. |
| Role instructions | Public API supported via context | Compose preset instructions with explicit task context. Researcher/reviewer are job descriptions, not lifecycle `role` enum values. |
| Narrow child tools | Supported with caveats | `allowed_toolsets` cannot broaden parent permissions. Empty values currently mean inheritance, not zero tools. |
| Status/result/steer/cancel | Source-supported API; product edge cases unverified | Orpheus owns resolving/starting states; host supplies status/wait/result/steer/cancel. Preserve only available partial results, unknown launch identity, and actual terminal states. Cancellation races need execution tests. |
| Clone profile memory and automatic skill learning | Outside current scope | Existing subagent behavior is preserved; it does not imply full profile cloning or guaranteed automatic learning. |

Primary evidence: [launch request and service](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/agent/subagent_lifecycle.py), [child construction and defaults](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/tools/delegate_tool.py), [child reasoning configuration](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/tools/delegate_tool_config.py), [plugin authoring guide](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins).

## Selection policy by entrypoint — user clarification

| Entrypoint | Preset/model/effort decision | Execution target |
|---|---|---|
| Subagent spawn | Existing parent LLM may choose; configured rules/Jev can also resolve fields | Native child beneath the active parent |
| Webhook | Rules or Jev only, before any work-session agent runs; no LLM fallback or bootstrap agent | New top-level work session |

This replaces the intermediate interpretation that all preset selectors or all field selectors must avoid LLMs. The latest user decision is entrypoint-specific. Fixed values and candidate constraints apply in both paths. True free-text generation is available only where the subagent entrypoint permits an LLM; webhook rules can map trusted values and Jev can select finite candidates.

## Proposed subagent integration boundary

1. The parent discovers preset identifiers, purposes, and permitted dynamic fields.
2. The parent supplies a task and explicit routing context. If its administrator-bound policy permits parent selection, it also chooses a preset; otherwise configured rules/Jev select the preset.
3. Orpheus validates parent-proposed dynamic fields or resolves them using configured rules/Jev. Jev selection and child execution are distinct operations.
4. Orpheus validates the complete result against a snapshot of the preset and the actual host capabilities.
5. The plugin calls `ctx.subagent_lifecycle.launch(...)` with supported settings and retains the returned handle.
6. The parent receives the preset revision, resolved settings, run identity, and eventual child result. Unsupported settings fail before any child starts.

Tool names and config syntax should be finalized during implementation. No need to override the built-in `delegate_task` tool, monkey-patch Hermes, or import its private child-construction functions.

The existing parent LLM supplies selections through launch-tool arguments; Orpheus validates candidates and cross-field compatibility. A separate selector LLM call is outside this draft’s selected design. Webhook preset/model/effort resolution uses only rules/Jev and cannot invoke the parent-proposal path.

Additional host constraints: the request's lifecycle `role` currently does not control recursion by itself; the underlying builder derives it from global delegation depth configuration. Per-launch working directory, per-tool blocks, and runtime timeout are explicitly rejected. `wait(timeout_seconds=...)` bounds a wait, not child execution. Orpheus must not present these as supported preset overrides. [Pinned child construction](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/tools/delegate_tool.py#L199), [request validation](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/agent/subagent_lifecycle.py#L218).

## System One / Jev integration

TypeSafe accepts `POST https://api.typesafe.ai/v1/systemone` authenticated with a Bearer API key. Requests carry `state`, `model`, and a named `questions` map. A Choice question supplies instructions and a mapping of allowed candidate IDs to descriptions; the answer contains the choice, probabilities, and confidence. Choice supports up to 255 options. The Python SDK is `typesafe-sdk`, with synchronous and asynchronous clients. [HTTP API](https://docs.typesafe.ai/api), [Choice](https://docs.typesafe.ai/primitives/choice), [Python client](https://docs.typesafe.ai/sdk/python/api/clients/sync).

This fits preset IDs, configured model IDs, and supported effort labels. “Choose any currently available model” can still use enum: construct candidates from the configured model inventory. That differs from allowing invented model names or arbitrary provider endpoints.

Jev does not generate free strings. Free-form generation needs an allowed subagent LLM path; it is rejected for webhook selection. Deterministic rule mappings and finite model inventories do not require free-text generation. Type-correct output is not a guarantee of a correct routing decision. [Model limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).

Questions in one request are evaluated independently. **Proposed design:** select a compatible `(provider, model, effort)` candidate tuple, or select the model first and then resolve effort from that model's supported options. Do not assume independently selected model and effort are compatible. Candidate counts exceeding 255 require explicit shortlisting/staging, not silent truncation. [API introduction](https://docs.typesafe.ai/introduction).

Credentials and account access are deployment prerequisites, not verified here. Resolve the TypeSafe key through an approved host secret/config mechanism during implementation; exact storage integration has not been verified. Never store keys in presets, selector inputs, or diagnostics. Pin a selector model version for evaluation and record the returned version. Treat low confidence, no-match, rate limits, missing credentials, and exhausted retries as selection outcomes with an explicit fallback policy. Do not convert a selector retry into another child spawn. Confidence thresholds need an Orpheus-specific evaluation; no published threshold establishes our accuracy. [Quickstart](https://docs.typesafe.ai/introduction/quickstart), [models](https://docs.typesafe.ai/models), [confidence routing](https://docs.typesafe.ai/patterns/confidence-routing).

TypeSafe publishes a [Hermes skill-suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion), which provides a relevant routing precedent. It is not a preset-based subagent launcher and does not close Hermes's effort-setting gap.

## Unproven subagent plugin-only reasoning-effort approach

The earlier direct-API finding does not establish that every plugin-only route is impossible. Public `llm_request` middleware can rewrite provider request arguments. The public `subagent_start` hook includes child session/subagent identifiers and the task goal. In the pinned construction path, that hook runs before the lifecycle service submits the child for execution. A plugin could prepare a pending selection, bind it to the child in the start hook, and use session-scoped middleware to apply effort before its first provider call. [Start hook ordering](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/tools/delegate_tool.py#L331), [lifecycle launch ordering](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/agent/subagent_lifecycle.py#L277), [public middleware contract](https://hermes-agent.nousresearch.com/docs/developer-guide/middleware).

This is a design inference, not a verified launch mechanism. It remains blocked until a supported race-free binding and fail-closed enforcement mechanism are demonstrated. The start hook does not forward the lifecycle request's `correlation_id` or `metadata`; matching on task text alone is insufficient. The proof of concept must establish a supported, race-free binding for identical simultaneous tasks and plugin-host isolation. It must also cover provider-specific effort payloads, fallback model changes, cleanup, and resumed/retried calls. Request rewriting alone may differ from native reasoning configuration used elsewhere in Hermes. Define and verify whether side LLM calls such as context compression are excluded or included; do not accidentally apply task effort to unrelated auxiliary calls.

Middleware errors are fail-open by documented design. A required effort cannot silently become the parent's default if the adapter fails. An implementation must demonstrate a supported fail-closed launch/request policy or reject that host/provider combination. Merely catching errors or setting a best-effort middleware field is not enough to satisfy the product contract. Optional iteration limits remain a separate gap; this request adapter does not enforce agent-loop budgets.

## Preferred subagent upstream extension

Propose optional per-launch `reasoning_effort` support on the public request. A candidate precedence is explicit request > delegation configuration > parent; the exact policy must be agreed upstream. Validate the selected provider/model combination and verify the effective provider request, rather than merely accepting a string in configuration. Preserve existing defaults when the field is absent and reject unsupported combinations clearly.

If maximum iterations becomes a requirement, expose an optional positive `max_iterations` with documented bounds and define it as agent loop iterations, not a count of individual tool calls or user messages. Separately resolve the current lifecycle path's use of the constant rather than the normal delegation setting. These are proposed changes, not existing API features.

Use feature/capability detection against the installed host. A version label alone is insufficient proof that an extension is present and working. Full-scope readiness requires executed integration evidence on a compatible Hermes build, whether using an upstream field or the middleware alternative.

## Approaches considered

| Approach | Assessment |
|---|---|
| Public lifecycle plugin plus small upstream extension | Preferred clean contract for effort and optional iteration budgets; preserves native parent/child lifecycle. |
| Public child-start hook plus LLM request middleware | Plausible plugin-only effort path; requires explicit proof of correlation, isolation, fallback and enforcement. No live proof yet. |
| Plugin-only first release with dynamic model with effort not configurable per preset | Feasible reduced scope, but does **not** fulfill dynamic effort; presets declaring effort must be rejected. Requires an explicit product scope choice. |
| Separate Hermes CLI subprocess per preset | Can expose different CLI controls, but adds process, cancellation, result, and approval integration and may change memory/profile semantics. Not established as equivalent to native children. |
| Temporarily mutate global config or patch child objects | Reject as architecture: concurrent launches can interfere and private API compatibility is not guaranteed. |

## Validation needed before implementation can be called complete

- Load/discover presets and confirm fixed, enum, free, missing, duplicate, and stale-revision cases against the product invariants.
- Run two simultaneous children with different models/efforts and inspect effective requests; verify parent and unrelated children keep their settings.
- Verify provider/model/effort compatibility, unavailable credentials, and unsupported host fields fail before spawn.
- Exercise LLM malformed outputs and Jev low-confidence/no-match/429/timeout cases; assert no unintended fallback or duplicate child.
- Verify tool restrictions, including empty toolset behavior, and distinguish job-role instructions from delegation-depth permissions.
- Exercise child success, partial completion, failure, steer, cancellation races, and process exit; retain native statuses without claiming recovery.
- Evaluate Korean and English task routing on a curated task set, including easy/complex and ambiguous tasks. Measure correctness, latency, and cost with account access; no benchmark claims are made here.
- Verify existing skill and memory behavior is unchanged. This assessment does not establish a particular memory-provider hook's persistence behavior.

No installed-plugin tests or live selection calls were run during this assessment. Isolated webhook source probes are documented separately. The next concrete step is to settle field-mode/selector choices and run a bounded middleware proof of concept. Prefer the upstream API addition if native effort semantics cannot be preserved through supported middleware.
