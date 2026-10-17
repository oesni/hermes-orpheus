# Webhook session presets: feasibility and verification

Date: 2026-10-17. Hermes revision: `7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357`.

## Verdict

**Pinned source inspection and isolated stub probes indicate a plugin-only route for selecting model/provider/effort before creating a webhook work session:** mount an Orpheus endpoint on the API-server platform and invoke the authenticated public `POST /v1/runs` contract. Source inspection and isolated probes support this route. No installed-plugin, live HTTP, real-provider, or Jev integration test has been performed; full product acceptance remains unverified.

The existing native `/webhooks/...` dispatch cannot obtain the same behavior by returning model settings from its public dispatch hook. These are distinct integration paths.

## Entrypoint policy

| Entrypoint | Preset selection | Dynamic model and effort |
|---|---|---|
| Subagent spawn inside an active session | Existing parent LLM allowed; configured rules/Jev also allowed | Same policy, constrained by preset and host capabilities |
| Webhook before a new task session | Rules or Jev only | Rules or Jev only; no bootstrap LLM or LLM fallback |

The selected task agent may execute normally after webhook selection. The restriction applies to routing, not task execution. Fixed bindings are rules. Jev chooses finite candidates; it does not generate arbitrary model names.

## Public integration flow

1. The plugin uses `ctx.register_platform_handler("api_server", factory)` to add an Orpheus route to the API-server application before its router freezes.
2. The handler authenticates the delivery, applies configured authorization and event filters, and reconciles its delivery identifier.
3. It snapshots the preset registry and resolves preset/model/provider/effort through rules or Jev. It validates the complete combination and stores the selection outcome.
4. It calls authenticated `POST /v1/runs` over HTTP with a new session and the resolved `model`, `provider`, and `model_options.reasoning_effort`.
5. It associates the resulting run/session identity with the delivery and reports observed runtime settings separately from requested settings. Result delivery and reconciliation are Orpheus integration responsibilities.

The public plugin registration mechanism and API fields are documented in the [platform-handler guide](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins#register-native-platform-handlers-any-platform) and [API-server guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server). Steps 2–5 describe the proposed Orpheus implementation, not shipped behavior.

## Pinned source evidence

| Surface | Finding |
|---|---|
| [API-server mounting](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/gateway/platforms/api_server.py#L4502) | Plugin handlers receive the application before server startup/router freeze. |
| [Run request decoding](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/gateway/platforms/api_server_runs.py#L743) | Reads requested model/provider/options; forwards them into launch at lines 805–811. |
| [Runtime selection](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/gateway/platforms/api_server.py#L2210) | Resolves requested provider and target model for a fresh session without a model lock or route alias. |
| [Agent construction](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/gateway/platforms/api_server.py#L2307) | Passes decoded reasoning configuration and selected runtime into agent construction. |
| [Reasoning decoder](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/gateway/platforms/api_server_request_options.py#L13) | Accepts reasoning effort; invalid values can be ignored, requiring Orpheus prevalidation. |
| [Native dispatch hook](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/gateway/run_inbound_hooks.py#L68) | Consumes allow/skip/rewrite-text, not model/provider construction overrides. |
| [Request dispatch](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/agent/turn_api_call.py#L88) | Middleware request changes still use the original agent transport and API mode. |

`post_gateway_admission` consumes handled/reply results and fails open; `on_session_start` is observational. Neither establishes a public session-construction override. Middleware can rewrite a request's model but does not prove coherent replacement of agent identity, provider/client, context configuration, or API mode. The pinned native webhook adapter does not wire its application through the same plugin-handler mechanism.

## Conditions and remaining acceptance gaps

- Enable the API-server platform and configure a new Orpheus webhook URL. This is not transparent retrofitting of the existing native webhook URL.
- Authenticate the custom handler itself. Built-in API handlers authenticate individually; arbitrary plugin routes do not inherit blanket bearer authentication. Call the authenticated public API rather than private adapter functions.
- Keep profile/principal, credentials, and API destination administrator-controlled. Webhook payloads cannot select arbitrary authority or endpoints.
- Use a new session. Existing session overrides/persisted models may supersede request values; model-route aliases can also change resolution. Validate or deliberately resolve aliases and inspect effective runtime settings.
- Validate model/effort compatibility before launch. The decoder accepting an effort is not proof that every provider honors it.
- Distinguish selected initial model from runtime fallback. The API retains configured fallback behavior. Preset restrictions and effort compatibility must hold through fallback; enforcement and observability need integration proof before full acceptance.
- Implement custom ingress filtering, deduplication, receipt behavior, result delivery, and restart reconciliation explicitly. Existing native webhook guarantees are not automatically inherited. An ambiguous API submission must not trigger a blind second run. The pinned `/v1/runs` implementation has durable `Idempotency-Key` lookup/reservation, and its endpoint documentation describes exact-payload replay scoped to the authenticated profile/credential. This is a useful reconciliation primitive, not unlimited exactly-once delivery: retention expiry, credential changes, and request fingerprints must be accounted for. See [pinned run API documentation](https://github.com/NousResearch/hermes-agent/blob/7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357/website/docs/user-guide/features/api-server.md#L477).
- Verify normal top-level profile memory/skill behavior independently from subagent behavior. No new profile cloning or automatic learning capability is implied.

These gaps do not require assuming a core patch, but they prevent calling the full specification implemented or proven. Subagent effort remains a separate public-lifecycle gap described in [the main assessment](feasibility.md).

## Verification performed

[Evidence bundle](evidence/webhook-model-routing/README.md) contains a reproducible probe, recorded output, and source SHA-256 manifest. Six output groups passed: actual upstream middleware execution and AST-extracted hook/request/runtime functions with stub registry/provider/transport, plus AST checks of API forwarding and constructor keywords. Executed probes establish routing and decoding behavior under their stub assumptions; AST checks establish static keyword forwarding only. Actual provider effort application remains unverified. Neither constitutes an end-to-end deployed plugin.

Before release, execute authenticated custom endpoint → public run API → fresh session → first provider request, with concurrent distinct presets; verify failures, aliases, fallback, deduplication, ambiguous submissions, restart reconciliation, and effective effort. Test webhook routing with LLM selection disabled and demonstrate no bootstrap or fallback LLM request. Jev credentials and paid-model calls were not used in this assessment.
