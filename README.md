# hermes-orpheus

Execution presets for Hermes native subagents and webhook-created sessions. This implementation uses the original reviewed `inventory → fields → compatible_settings → policies` interface.

- [Requirements](docs/spec/subagent-presets.md)
- [Design](docs/design.md)
- [Implementation status and limits](docs/implementation.md)
- [Design and implementation reviews](docs/reviews/README.md)
- [Hermes compatibility extension](compat/README.md)

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

Install the package into the same Python environment that runs Hermes:

```sh
uv pip install --python /path/to/hermes/.venv/bin/python /path/to/hermes-orpheus
hermes plugins enable hermes-orpheus
```

The package exposes the public `hermes_agent.plugins` entry point. Configure the following in the active Hermes profile's configuration, using your own absolute paths:

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

The [preset example](examples/presets.yaml) uses the original interface. The [deployment example](examples/deployment.yaml) intentionally denies execution until an operator verifies the exact provider/model/effort settings. Credentials are referenced through environment variable names; do not place tokens in preset definitions.

## Subagents

The tools are `orpheus_presets`, `orpheus_spawn`, `orpheus_status`, and `orpheus_cancel`. The existing parent may propose a preset and dynamic values only when its administrator-bound policy permits it. Rules/Jev policies reject parent overrides.

For the included preset, the parent can request:

```json
{"task":"Analyze this problem","preset_id":"analyst","proposals":{"effort":"high"}}
```

The model is fixed by the preset, and `high` selects its `complex` tuple. Missing or ambiguous choices fail before launch. Tool access cannot exceed the verified deployment scope.

**Pinned stock Hermes does not expose per-subagent effort.** Every explicit effort setting is rejected on that host. The separate [companion source patch](compat/README.md) adds per-launch effort and fallback controls for the pinned revision. It is not automatically applied or submitted upstream. Even on a patched host, exact deployment settings require verification; source/constructor tests do not establish real-provider behavior. Model-only presets without an effort field can use the stock lifecycle, subject to the same deployment gates.

## Webhooks

Enable the Hermes API-server platform and register the plugin. Orpheus mounts `/orpheus/webhooks/{route_id}` and operator status/cancel/reconcile endpoints on that application. This does not modify native `/webhooks/...` routes. Use rules or Jev for every preset/model/effort choice before calling authenticated `POST /v1/runs` to create a fresh session.

Ingress supports SHA-256 HMAC over raw JSON body bytes, replay detection through durable body digests independent of unsigned delivery headers, typed body extraction and preselection filters. Receipts must be explicitly disabled in this initial implementation. Authentication, API target and operator credentials are separate; operator calls need a Bearer credential scoped to the route's stable security scope. Start from [webhook presets](examples/webhook-presets.yaml) and [webhook deployment](examples/webhook-deployment.yaml). See the implementation notes for supported configuration and limitations.

Jev uses `TYPESAFE_API_KEY` by default (override `jev_token_env` in deployment configuration). It receives only configured context projections and finite choices. Webhook routing never invokes a parent/selector LLM or falls back to one. No Jev or task-provider calls have been performed during development verification.

## Execution guarantees and verification scope

Launch intent and selections are persisted before submission. Duplicate webhook bodies reuse the original record. Ambiguous submissions remain `unknown` and are not automatically resubmitted; restart or polling cannot create replacement runs. Native ownership is checked through the public lifecycle before status/cancel access, and internal capability tokens are not returned to callers.

Tests cover actual Orpheus registry/resolver/plugin wiring, a local HTTP server representing the public Hermes run API, and the patched upstream constructor with dependencies stubbed. An installed live Hermes/provider integration, effective provider effort, and production deployment acceptance remain separate gates. No production gateway was changed.
