# hermes-orpheus

Execution presets for Hermes native subagents and webhook-created sessions. This implementation uses the original reviewed `inventory → fields → compatible_settings → policies` interface. Hermes core modifications are not required or shipped. Native presets select models and retain the host's existing effort behavior; webhook presets may select both models and effort through the public Run API.

- [Requirements](docs/spec/subagent-presets.md)
- [Design](docs/design.md)
- [Implementation status and limits](docs/implementation.md)
- [Design and implementation reviews](docs/reviews/README.md)

## Local development and configuration inspection

Requires Python 3.11+ and uv.

```sh
uv sync
uv run orpheus validate examples/presets.yaml --deployment examples/deployment.yaml
uv run orpheus inspect examples/presets.yaml
uv run pytest -q
uv build
```

`validate` checks configuration structure and quarantined definitions, not provider connectivity. `inspect` expands inventory references into concrete provider/model/effort tuples. No LLM or Jev request is made by either command.

## Install in a Hermes environment

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

Equivalent fallback environment variables are `ORPHEUS_CONFIG`, `ORPHEUS_DEPLOYMENT`, and `ORPHEUS_STATE_DIR`. Reload the plugin or restart the host after configuration changes; no live file watcher is installed. State defaults to `$HERMES_HOME/orpheus` (or `~/.hermes/orpheus`). Loading the plugin never launches work. With no preset configuration it registers discovery tools with an empty registry.

The [preset example](examples/presets.yaml) uses the original interface. The [deployment example](examples/deployment.yaml) intentionally denies execution until an operator verifies the exact native provider/model settings. Credentials are referenced through environment variable names; do not place tokens in preset definitions.

## Subagents

The tools are `orpheus_presets`, `orpheus_spawn`, `orpheus_status`, and `orpheus_cancel`. The existing parent may propose a preset and dynamic values only when its administrator-bound policy permits it. Rules/Jev policies reject parent overrides.

For the included preset, the parent can request:

```json
{"task":"Analyze this problem","preset_id":"analyst","proposals":{"model":"large"}}
```

The selected model reference `large` resolves to the preset's matching model tuple. Missing or ambiguous choices fail before launch. Tool access cannot exceed the verified deployment scope.

**Native subagent effort overrides are outside this release.** Omit `effort` from native preset fields and compatible tuples. The adapter rejects every explicit effort, including on hosts advertising an extension, and never sends `reasoning_effort` or per-launch `disable_fallback`. The host's existing reasoning configuration applies. Operators must verify provider fallback is disabled in the host configuration and authorize exact `{provider, model}` pairs. Per-child maximum turns and upstream patches are also outside scope. Presets declaring effort remain usable for compatible webhook routes.

## Webhooks

Enable the Hermes API-server platform and register the plugin. Orpheus mounts `/orpheus/webhooks/{route_id}` and operator status/cancel/reconcile endpoints on that application. This does not modify native `/webhooks/...` routes. Use rules or Jev for every preset/model/effort choice before calling authenticated `POST /v1/runs` to create a fresh session.

Ingress supports SHA-256 HMAC over raw JSON body bytes, replay detection through durable body digests independent of unsigned delivery headers, typed body extraction and preselection filters. Receipts must be explicitly disabled in this initial implementation. Authentication, API target and operator credentials are separate; operator calls need a Bearer credential scoped to the route's stable security scope. Start from [webhook presets](examples/webhook-presets.yaml) and [webhook deployment](examples/webhook-deployment.yaml). See the implementation notes for supported configuration and limitations.

Jev uses `TYPESAFE_API_KEY` by default (override `jev_token_env` in deployment configuration). It receives only configured context projections and finite choices. Webhook routing never invokes a parent/selector LLM or falls back to one. No Jev or task-provider calls have been performed during development verification.

## Execution guarantees and verification scope

Launch intent and selections are persisted before submission. Duplicate webhook bodies reuse the original record. Ambiguous submissions remain `unknown` and are not automatically resubmitted; restart or polling cannot create replacement runs. Native ownership is checked through the public lifecycle before status/cancel access, and internal capability tokens are not returned to callers.

Tests cover actual Orpheus registry/resolver/plugin wiring, a local HTTP server representing the public Hermes run API, and stock-shaped native lifecycle requests. An installed live Hermes/provider integration, effective provider effort, and production deployment acceptance remain separate gates. No production gateway was changed.
