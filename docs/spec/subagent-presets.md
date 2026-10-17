# hermes-orpheus: subagent and webhook session presets

Status: requirements draft, 2026-10-17. This document describes desired behavior, not implemented or verified functionality.

## Summary

hermes-orpheus provides reusable presets for subagents and new top-level sessions started by webhooks. Selection policy depends on the entry point: an existing parent LLM may choose a subagent's preset, model, and effort, while webhook sessions use only configured rules or TypeSafe's System One API (Jev) for all such choices before task execution. Declared field constraints and runtime capabilities apply to both paths.

## Scope and decision status

The user confirmed the project name, presets available to the same agent, task-appropriate subagent spawning, dynamic fields, complexity-sensitive effort, and automatic model choice. The latest clarification makes selection policy **entry-point-specific**: parent LLM choice is allowed for subagents already inside a session; webhook selection must use rules or Jev for preset identity, model, and effort, without an LLM selector. This supersedes earlier blanket no-LLM interpretations. The user identified System One through [TypeSafe's introduction to System One and Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev).

The fixed/enum/free field contract below is a **proposed design**: enum versus free selection was exploratory in the request. Error handling, configuration conventions, and lifecycle expectations are also proposals that make the draft actionable; they are not additional confirmed user requests. They become acceptance requirements if this draft is adopted.

This scope does not include a new UI, separate persistent Hermes profiles, automatic memory synchronization, automatic skill learning, or a replacement for Hermes's subagent runtime. Per-preset maximum turns is an optional candidate, not a confirmed requirement. Runtime support and extension requirements belong in the companion feasibility assessment.

## Behavior

### Presets and discovery

1. A single parent agent can discover and use multiple named presets without switching its active Hermes profile. The same preset registry is available to webhook routes starting new top-level sessions, with entry-point compatibility reported per preset. Preset selection alone does not replace an existing parent's identity, conversation, model, or profile settings.

2. Each preset exposes a unique stable identifier, a human-readable purpose, task selection guidance, role instructions, and its configurable fields. A parent can inspect enough information to distinguish, for example, a researcher from a reviewer before choosing either.

3. Preset discovery reports an empty collection when no presets are configured. The parent receives actionable guidance that a preset must be added before spawning through Orpheus; an empty collection does not trigger an arbitrary default child.

4. Invalid presets are identified by name and validation reason. They cannot be selected for spawning. One invalid preset does not make unrelated valid presets unavailable; duplicate identifiers make every conflicting definition unavailable until corrected.

5. **Confirmed selection constraint.** Selection policy is entry-point-specific. For subagents, the existing parent LLM may select a preset identifier after discovery, then propose model and effort where declared dynamic. For a new webhook session, configured rules or Jev must select preset identity, model, and effort; no LLM selector or LLM fallback is permitted. An administrator-configured fixed preset binding, including a webhook route binding, is a rule. One entry point's policy cannot be used to bypass the other's restrictions.

### Fixed and dynamic settings — proposed contract

6. **Proposed configuration contract.** A field has one declared mode: fixed, enum, or free. A fixed field has an administrator-configured value. An enum field has a nonempty candidate set and selection guidance. The set may be an explicit configured list or a snapshot of currently available host models / supported effort labels; discovery-generated candidates remain finite and validated. Free generation may be offered to the subagent parent-LLM path within declared types and constraints. Webhook rules and Jev do not support unconstrained generative fields; an incompatible preset is rejected for that entry point. Malformed or contradictory definitions are rejected.

7. Fixed values cannot be overridden by the parent, a selector, task text, or an instruction inside retrieved material. Only fields explicitly marked dynamic are eligible for selection.

8. Enum results must match an allowed value. A value outside the set, multiple values for a single-valued field, or an omitted required value is a resolution error. The caller sees which field failed; no child starts using a guessed replacement.

9. Free mode is not freedom to change arbitrary runtime settings. A parent-proposed model must still be usable through an authorized configured provider; proposed effort must be supported for that model. Credentials, provider endpoints, and permission boundaries are not free-selectable values. **Proposed rule contract:** rules may produce explicitly configured typed values or finite mapped values, but cannot invent arbitrary models. This is distinct from free generation and remains subject to runtime validation.

10. A model selection identifies its provider unambiguously. Model and effort combinations are validated together. A valid effort label for one model is not assumed to work for another, and an unsupported effort is not silently dropped.

11. **Confirmed requirement.** For subagents, the parent LLM or configured rules/Jev can choose effort to fit task complexity, such as lower effort for routine work and higher effort for complex analysis; the child must execute with the supported selected effort. For webhooks, rules/Jev choose effort and the new top-level session must execute with it. Guidance may be supplied by the preset author. A release offering only inherited effort does not satisfy this requirement. No execution path has yet been verified to fulfill it; see feasibility.

12. The initial candidate field set comprises child model/provider, reasoning effort, role instructions, and allowed toolsets. Only fields both declared dynamic and supported by the installed integration can vary. Actual support, especially reasoning effort, must be reported by feasibility and capability checks; listing a field here does not assert current Hermes support.

13. If per-preset maximum turns is adopted later, it is subject to the same fixed/dynamic constraints and must define what counts as a turn. An installation that cannot apply it rejects that setting explicitly; it must never accept the value and launch with an undisclosed default.

### Dynamic field resolution

14. The configuration identifies selection policy separately for subagent and webhook entry points and distinguishes preset choice from field resolution. Subagent selection may use the existing parent LLM or an explicitly configured rule/Jev path. Webhook preset choice and field resolution use only rules or Jev. Selecting an execution model does not change an existing parent model, and no webhook selection-only LLM request is permitted.

15. For subagents, the parent may provide a preset identifier and proposed values only for fields declared dynamic. Those proposals are validated and do not override fixed values or enum constraints. An explicitly configured rule/Jev policy is not silently bypassed by parent guesses. This parent-LLM path is unavailable to webhook callers, including through a claimed preset identifier or model/effort values in their payload.

16. System One can choose among finite candidate values or finite complete setting combinations. It is not promised as an unconstrained text generator. Model choice from a discovered finite inventory can use System One. Genuinely free generative fields require the permitted subagent LLM path; a webhook configuration requiring such generation is rejected before session execution. A Jev failure never invokes an LLM in the webhook path.

17. Where several fields vary, the final combination must satisfy all constraints together. Independently valid model and effort choices that are incompatible together produce an error, not a partially applied launch.

18. A selector receives the task description, explicitly provided task context, preset guidance, and relevant candidate descriptions. The caller is informed which backend receives this information. Parent conversation history, secrets, and profile memory are not automatically sent wholesale to an external selection service.

19. Selection reports the chosen preset identifier, matched rule or Jev choice or parent-LLM selection, resolved values, entry-point policy, and separate selector/resolver identities. A textual explanation is included only if available; Orpheus does not invent one. The record distinguishes requested, resolved, launch-accepted, and observed effective settings. Unobservable effective settings are unverified. Runtime provider/model fallback is reported separately from selector fallback, must respect configured model constraints, and must revalidate effort for the fallback model.

20. Authentication failures, offline services, timeouts, invalid outputs, and unavailable candidates produce distinguishable selection errors. No child starts on a failed selection. Any fallback requires an explicit configured policy and is disclosed in the returned selection record; the default is no fallback.

### Spawn and parent interaction

21. A subagent spawn request supplies a nonempty task, preset identifier when parent selection is enabled, and optional explicit context and dynamic-field proposals. Rule/Jev subagent policies may instead accept routing inputs and resolve the preset. Unknown identifiers or fields, forbidden overrides, and missing required values produce actionable errors before execution. These subagent inputs do not define the webhook selection contract.

22. After successful selection and validation, the child receives the task, explicit context, and preset role instructions, along with the supported resolved execution settings. Preset instructions do not erase inherited Hermes safety or project rules.

23. The child has a separate conversation under Hermes's existing subagent behavior. Orpheus does not promise that the parent's full transcript, profile memory, skills, or automatic learning process is cloned. Existing memory and skill behavior remains the runtime's behavior unless a separate feature explicitly changes it.

24. Allowed tools remain within the parent's permitted tool scope and Hermes's child restrictions. Orpheus validates the requested set against those capabilities before launch. An omitted set means inherit; an explicit empty set requesting zero tools is rejected as unsupported on hosts where it means inheritance, including the reviewed revision. A preset requesting broader access is rejected or reported as incompatible before spawn; it does not grant new authority.

25. Parent callers can distinguish resolving, starting, running, completed, failed, cancelled, and unknown work. A spawn acknowledgment means only that the runtime accepted a child, not that the task succeeded. The caller receives a run identifier once one exists.

26. The parent can obtain the child's result and final execution status through the supported Hermes lifecycle. Completion reporting includes preset identity and requested/resolved/observed settings alongside the child result; runtime fallbacks and unknown effective values remain visible. Failure and cancellation preserve any available partial result and are never labeled successful completion.

27. Cancellation before launch prevents subsequent child creation once cancellation is acknowledged. Cancellation after launch uses the runtime's supported cancellation semantics; a request is not reported as completed cancellation until confirmed. If completion wins the race, the caller sees the completed outcome.

28. Orpheus does not automatically respawn a child after a launch timeout or an ambiguous response. The caller receives the uncertainty and any known run identifier so an already-running task is not duplicated. Any user-requested retry is a distinct run unless runtime-supported deduplication proves otherwise.

29. Concurrent runs keep their preset selections, task contexts, results, and identifiers separate. Resolving a model or effort for one task cannot alter another task or a shared parent default.

30. A run uses one consistent preset revision throughout selection and launch. Editing or removing that preset affects subsequent requests, not already accepted runs. If the integration cannot preserve that revision for a pending request, it reports a stale-preset error and requires a new selection instead of mixing revisions.

31. Unavailable lifecycle operations, unsupported runtime settings, and missing integration capabilities are reported explicitly. The plugin does not claim persistence or recovery across Hermes restarts unless the installed runtime supports and verifies it; an unresolvable old run is shown as unavailable or unknown rather than successfully completed.

### Preset routing — proposed acceptance contract

32. Rules declare their matching conditions and explicit evaluation priority. The first matching rule selects one preset; equal priorities, ambiguous ordering, invalid predicates, and references to unavailable presets are configuration errors. Given identical routing inputs and the same configuration revision, rule selection returns the same outcome. Task or event text cannot replace the configured rules.

33. A rule configuration declares a no-match policy. The proposed default is a visible routing failure with no execution. An explicit default preset or a transition to Jev is allowed only when configured and recorded; the absence of a match never silently invokes an LLM.

34. Jev preset selection chooses one identifier from a finite snapshot of valid, entry-point-compatible presets. Operators can inspect the candidate descriptions and event/task fields sent to Jev. Authentication failures, timeouts, invalid responses, and unavailable or out-of-set choices are distinguishable failures. No run starts unless the configured fallback resolves to valid settings and the record discloses its identity and reason. Webhook fallback is limited to rules or Jev; it cannot invoke an LLM. Field-resolution errors follow the same entry-point policy.

35. For rule-based selection, only configured routing inputs influence matching. A parent may provide a task description, but arbitrary claimed privilege or trusted event attributes in that text do not become authoritative metadata. For webhooks, authenticated route/event metadata is distinguished from untrusted payload text; payload-provided preset/model/effort values cannot override the configured selection policy. Selection does not grant additional permissions.

### New webhook sessions

36. **Confirmed requirement.** An accepted webhook that starts a new top-level Hermes session can apply a preset from the shared registry. Its execution model is resolved dynamically where configured, using the same fixed/dynamic constraints as subagent execution. This is a requested capability, not a claim that the installed Hermes plugin interfaces already support it.

37. Webhook authentication, route authorization, event filtering, and applicable delivery checks occur before preset selection or external selector calls. Rejected events do not start a session or send payloads to Jev or a field resolver. Existing native routes and their receipt hooks remain unchanged. A custom Orpheus route must explicitly implement configured receipt behavior or report its absence as a limitation; receipts remain best-effort and do not establish task completion or successful session creation.

38. A webhook route declares its rule/Jev selection policy and permitted routing inputs for preset identity and dynamic fields, including model and effort. An administrator may use a fixed binding, conditional rules, or Jev, including a configured combination of rules and Jev. Event payloads cannot supply arbitrary preset identifiers, credentials, provider endpoints, or settings that bypass that policy. Only configured necessary context is disclosed to Jev; neither the full payload nor secrets are automatically sent. No LLM selection or LLM-generated field resolution is allowed on this entry point.

39. Preset selection and field resolution complete before the new session makes its first task-execution model request. That request must use the accepted model/provider and supported effort settings. Starting with defaults and switching on a later turn does not satisfy this requirement. Jev selection requests are identified separately from task execution; the prohibition on an LLM selector does not prohibit the selected task agent from executing its assigned work after launch.

40. A webhook session reports requested, resolved, launch-accepted, and observed effective settings, including the preset/configuration revision and selection method. Unsupported settings or inability to enforce required settings produce an explicit failure before task execution, never a successful-looking session with silently inherited defaults. Unobservable settings remain unverified. Cross-provider model choice requires the selected authorized provider to be usable; changing only a display model name does not meet the requirement.

41. A delivery identity within its authenticated route scope identifies one logical request. The route must establish that identity from authenticated material or apply replay detection that also catches the same authenticated body with altered unsigned delivery identifiers. An unsupported authentication/replay contract makes the route incompatible before admission. Duplicate deliveries expose the existing outcome or pending state and reuse its recorded preset revision and resolved settings; they do not reselect after configuration changes or create another session. An ambiguous launch outcome is reported as unknown pending reconciliation. If the installed integration cannot provide this behavior, the limitation blocks a supported deduplicated webhook path rather than authorizing a blind retry.

42. The route distinguishes creating a new session from resuming an existing session. This feature applies selection to new sessions only. Resumed sessions retain their established preset and execution settings; a later event or rule change does not silently reroute them. Explicit migration or rerouting of an existing session is outside this draft's scope.

43. A new top-level webhook session follows the route's administrator-configured Hermes profile's normal memory and skill behavior. It is not a subagent and must not inherit the subagent-only memory-skipping or restricted-tool assumptions merely because both entry points use a preset. This feature does not promise cloning another session's transcript, memory synchronization, or automatic skill learning beyond the host profile's normal behavior.

44. Concurrent webhook sessions and subagents retain independent resolved models, providers, effort settings, task contexts, and results. Selecting a model for one webhook cannot mutate shared defaults, a live parent, another session, or a later unrelated request. Preset instructions and tools remain subject to the selected entry point's existing authorization and project rules.

45. Operators can distinguish rejected, resolving, starting, running, completed, failed, cancelled, and unknown webhook outcomes and correlate them with the authenticated delivery and session identifier when available. Authentication rejection, selection failure, and launch failure are different outcomes. Cancellation and ambiguous launch handling follow the same non-duplication and confirmation principles as invariants 27–28; cancellation support is reported per entry point rather than assumed from the subagent API.

46. Capability reporting distinguishes subagent launch, new webhook session launch, dynamic model/provider selection, effort application, and delivery/session recovery. A plugin-only feasibility finding for one entry point or field is not presented as proof for another. Missing public integration support remains visible; this requirements draft does not authorize undocumented runtime modification or claim a completed implementation.

Requirements 1, 5, 11, 36, and dynamic model selection express confirmed goals. The confirmed selection boundary is between entry points, not between preset identity and individual fields: parent LLM selection is permitted for subagents, while webhook selection uses rules/Jev only throughout. Rule ordering, failure behavior, deduplication, observation, and lifecycle details are proposed acceptance behavior.

## Open questions

- Begin with enum-only fields, or also support constrained free generation on the subagent parent-LLM path?
- Which rule predicates, typed mappings, explicit default policies, and Jev fallback policies should be supported first?
- Which dynamic fields beyond model and effort are needed in the first release, and should maximum turns become a requirement?
- What task context is necessary for System One selection, and what fallback policy, if any, should operators be able to configure?

These questions do not block documenting feasibility. Unresolved or unsupported choices must remain visible rather than being represented as implemented behavior.
