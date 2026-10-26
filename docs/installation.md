# Installation and operation

[Back to README](../README.md) · [Configuration authoring guide](configuration-guide.md)

## Install the plugin

Clone `https://github.com/oesni/hermes-orpheus` and enter the repository directory first.

For a managed Hermes installation, use its native directory-plugin loader. For an initial installation, run the following from the Orpheus repository root. It refuses an existing destination so copying cannot leave stale modules from an earlier version:

```sh
(
  orpheus_plugin_dir="${HERMES_HOME:-$HOME/.hermes}/plugins/hermes-orpheus"
  if [ -e "$orpheus_plugin_dir" ] || [ -L "$orpheus_plugin_dir" ]; then
    printf '%s\n' 'Orpheus already exists; this recipe is for a fresh installation only.' >&2
    exit 1
  fi
  mkdir -p "$orpheus_plugin_dir" &&
    cp plugin.yaml __init__.py "$orpheus_plugin_dir/" &&
    cp -R orpheus "$orpheus_plugin_dir/"
)
```

Use the selected profile's actual `HERMES_HOME` when installing into a named profile. The manifest declares `PyYAML>=6.0.2,<7` and `aiohttp>=3.11,<4`. On the verified managed Hermes CLI, `hermes plugins enable` resolves and installs declared dependencies through Hermes's package manager as part of activation. Manifest parsing alone only validates the declarations. Let Hermes manage these dependencies; do not manually run pip against its managed runtime. The directory entry point imports its bundled package within Hermes's plugin namespace.

For a conventional Python environment that you manage, installing the package into the same environment that runs Hermes is an alternative:

```sh
uv pip install --python /path/to/hermes/.venv/bin/python /path/to/hermes-orpheus
```

This alternative exposes the public `hermes_agent.plugins` entry point. Choose one installation method for a profile to avoid duplicate plugin discovery.

For either method, configure the following in the active Hermes profile's configuration, using your own absolute paths, then enable the plugin with `hermes plugins enable hermes-orpheus` (use `hermes -p PROFILE plugins enable hermes-orpheus` for a named profile):

```yaml
plugins:
  entries:
    hermes-orpheus:
      enabled: true
      settings:
        config_path: /path/to/presets.yaml
        deployment_path: /path/to/deployment.yaml
        state_dir: /path/to/private/orpheus-state
```

Equivalent fallback environment variables are `ORPHEUS_CONFIG`, `ORPHEUS_DEPLOYMENT`, and `ORPHEUS_STATE_DIR`. Reload the plugin or restart the host after configuration changes; no live file watcher is installed. State defaults to `$HERMES_HOME/orpheus` (or `~/.hermes/orpheus`). Loading the plugin never launches work. With no preset configuration it registers all four Orpheus tools over an empty registry. Loading also initializes the state directory, SQLite database, and retention worker.

The [preset example](../examples/presets.yaml) uses parent-selected native subagent presets. The [deployment example](../examples/deployment.yaml) intentionally denies execution until an operator verifies the exact native provider/model settings. Credentials are referenced through environment variable names; do not place tokens in preset definitions.

## Verify and start a session

Run `hermes plugins doctor hermes-orpheus --ci` to check discovery and tool registration. For named profiles, use `hermes -p PROFILE` consistently for these commands. A passing doctor check does not verify provider access or authorize deployment tuples.

Ensure the `orpheus` toolset is enabled for the parent session. Preserve any existing platform toolsets; add Orpheus rather than replacing them. Child toolsets must also be available to the parent. Start a new session after enabling the plugin.

### Turn off built-in delegation

Turn off the Hermes `delegation` toolset, which provides the built-in `delegate_task` tool, in sessions that use Orpheus. While `delegate_task` is available, the agent can delegate through it instead of `orpheus_spawn`. That child gets no preset, policy, or deployment check. Its model comes from the Hermes delegation settings (`delegation.backend`, `delegation.model`, and `delegation.provider`), or from the parent when those are unset.

Orpheus does not need the toolset. It launches children through the plugin lifecycle API, not through `delegate_task`. A session started without `delegation` launched and finished an Orpheus child.

To turn it off on every platform, add `delegation` to `agent.disabled_toolsets` in the profile's configuration. Keep any entries already in the list. Also set `delegation.orchestrator_enabled` to `false`:

```yaml
agent:
  disabled_toolsets:
    - delegation
delegation:
  orchestrator_enabled: false
```

To turn it off on one platform only, remove `delegation` from that platform's toolsets with `hermes tools`, and still set `delegation.orchestrator_enabled` to `false`. Start a new session after either change.

The orchestrator setting covers Orpheus children. Hermes picks a child's role from its depth and ignores the role in the launch request. If `orchestrator_enabled` is `true` and `delegation.max_spawn_depth` is 2 or more, an Orpheus child becomes an orchestrator. Hermes then gives it `delegate_task` again, even when the parent has `delegation` turned off. With `orchestrator_enabled: false`, every child is a leaf and has no `delegate_task`.

Use the [configuration authoring guide](configuration-guide.md) to turn the examples into a usable configuration. It covers exact model authorization, compatible tuples, context declarations, and the first discovery/spawn/status check. Do not mark fallback disabled or a model verified simply to bypass preflight.

## Subagents

The tools are `orpheus_presets`, `orpheus_spawn`, `orpheus_status`, and `orpheus_cancel`. The existing parent may propose a preset and dynamic values only when its administrator-bound policy permits it. This is checked separately for each stage: `preset_id` is accepted only with a `parent` preset selector, and `proposals` only with a `parent` field resolver. Fixed, rules, and System One stages reject their corresponding parent input, including `proposals: {}`. A parent preset selector combined with a System One field resolver accepts `preset_id` but requires omitting `proposals`.

For the included preset, the parent can request:

```json
{"task":"Analyze this problem","preset_id":"analyst","proposals":{"model":"large"}}
```

The selected model reference `large` resolves to the preset's matching model tuple. Parent field proposals must identify exactly one compatible combination; omitted proposals succeed only if the preset has one combination. Ambiguous choices fail before launch.

When a preset fixes `allowed_toolsets`, every entry must also appear in the deployment's `subagent.allowed_toolsets` and be available to the parent. If the preset field is omitted, the child inherits host/parent toolsets; the deployment list does not limit inherited tools. An empty preset toolset list is rejected, not treated as a no-tools sandbox.

Native launch accepts at most 16,000 task characters and 32,000 rendered context characters. The context includes the `Preset instructions:` block and JSON-encoded context, so leave space for instructions and JSON escaping when setting context bounds. Set `task.text.max_length` to at most 16000. These launch checks happen after selection; an oversized request may already have incurred a System One request before failing with `input_too_large`.

**Native subagent effort overrides are outside this release.** Omit `effort` from native preset fields and compatible tuples. The adapter rejects every explicit effort, including on hosts advertising an extension, and never sends `reasoning_effort` or per-launch `disable_fallback`. The host's existing reasoning configuration applies. Operators must verify provider fallback is disabled in the host configuration and authorize exact `{provider, model}` pairs. Per-child maximum turns and upstream patches are also outside scope. Presets declaring effort remain usable for compatible webhook routes.

## Webhooks

Enable the Hermes API-server platform and register the plugin. Orpheus mounts `/orpheus/webhooks/{route_id}` and operator status/cancel/reconcile endpoints on that application. This does not modify native `/webhooks/...` routes. Use fixed configuration, rules, or System One for every preset/model/effort choice before calling authenticated `POST /v1/runs` to create a fresh session.

Ingress supports SHA-256 HMAC over raw JSON body bytes, replay detection through durable body digests independent of unsigned delivery headers, typed body extraction and preselection filters. Receipts must be explicitly disabled in this initial implementation. Authentication, API target and operator credentials are separate; operator calls need a Bearer credential scoped to the route's stable security scope. Start from [webhook presets](../examples/webhook-presets.yaml) and [webhook deployment](../examples/webhook-deployment.yaml). See the [implementation notes](implementation.md) for supported configuration and limitations.

Use `kind: systemone` for System One Choice API routing in `preset_selector`,
`field_resolver`, and referenced `resolver_nodes`. The `model` remains an endpoint-supported
model identifier; the resolver kind names the protocol, not a particular model.
The complete [System One example](../examples/systemone-presets.yaml) lets the parent
choose a preset and System One choose its model tuple:

```yaml
field_resolver:
  id: fields
  kind: systemone
  model: typesafe/jev-1.14
  projection_fields: [task.text]
```

The deprecated `kind: jev` spelling remains a compatibility alias. Both spellings
use the same validation, projections, finite choices, retries, and fallback rules.
Compiled policies normalize the alias to `systemone`; source snapshots and revision
hashes retain the original configuration. Canonical `systemone_endpoint` and `systemone_token_env`
deployment keys replace the deprecated `jev_endpoint` and `jev_token_env` aliases.
Equal old/new duplicates are accepted; conflicting values fail validation without exposing
the values. A custom endpoint still requires an explicit credential variable binding.
Model identifiers such as `typesafe/jev-1.14` are unchanged.
Python integrations use `orpheus.systemone.SystemOneClient`, the Resolver
`systemone_client` argument/instance attribute, and `orpheus.deployment.DEFAULT_SYSTEMONE_ENDPOINT`
and `validate_systemone_endpoint`. Compatibility aliases remain:
`orpheus.jev.JevClient`, the Resolver `jev_client` argument/property, and
`orpheus.deployment.DEFAULT_JEV_ENDPOINT` / `validate_jev_endpoint`
(the last two are also re-exported from `orpheus.jev`).

Diagnostic codes intentionally use the new protocol name, including for legacy input:
`invalid_jev_endpoint` → `invalid_systemone_endpoint`,
`jev_endpoint_requires_token_env` → `systemone_endpoint_requires_token_env`, and
`invalid_jev_token_env` → `invalid_systemone_token_env`. Integrations matching these
codes must update their checks; the old diagnostic strings are not aliases.

The System One client uses `TYPESAFE_API_KEY` and `https://api.typesafe.ai/v1/systemone` by default. Configure the full endpoint and credential environment variable in the operator deployment file. For OpenRouter System One:

```yaml
systemone_endpoint: https://openrouter.ai/api/v1/systemone
systemone_token_env: OPENROUTER_API_KEY
```

The policy's `model` must be an identifier supported by that endpoint, such as `typesafe/jev-1.14`. Use your existing environment variable name if different; store its value outside the repository. A custom endpoint requires an explicit `systemone_token_env`, so changing the host cannot silently reuse the default credential variable. Setting only `systemone_token_env` (or its legacy alias) retains the default Typesafe endpoint and sends that credential there. Always set both endpoint and token-variable keys together for another provider. Only HTTPS endpoints without embedded credentials, query strings, or fragments are accepted, and redirects are disabled.

The System One client receives projected inputs plus finite choice descriptions. Preset selection sends purpose and guidance; field selection sends those descriptions and each candidate's resolved settings, including fixed instructions, toolsets when set, and provider/model identities. Keep secrets out of all of these fields. Webhook routing never invokes a parent/selector LLM or falls back to one. The [live Jev smoke test](evidence/jev/README.md) verified resolver-only preset and compatible model/effort tuple selection against OpenRouter System One. Task model identifiers are synthetic; no downstream task model was launched. The default Typesafe endpoint was not tested live, and native subagent execution still rejects explicit effort.

## Execution guarantees and verification scope

Launch intent and selections are persisted before submission. Duplicate webhook bodies reuse the original record. Ambiguous submissions remain `unknown` and are not automatically resubmitted; restart or polling cannot create replacement runs. Native ownership is checked through the public lifecycle before status/cancel access, and internal capability tokens are not returned to callers.

Tests cover actual Orpheus registry/resolver/plugin wiring, a local HTTP server representing the public Hermes run API, and stock-shaped native lifecycle requests. The [local Hermes smoke test](evidence/local-hermes/README.md) verified native preset discovery, child launch and a successful review result. It did not independently observe the effective provider model or effort. These linked receipts describe bounded local tests, not a guarantee for every provider or gateway deployment.
