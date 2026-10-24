# Configure Orpheus with an agent

Give this document to your agent together with your desired roles, available models,
and execution environment. It explains how to produce and validate configuration;
reading it does not authorize installing plugins, changing host settings, calling
paid APIs, or launching tasks. See [installation](installation.md) for setup.

## Start with the execution entrypoint

| Requirement | Native subagent | Webhook → Hermes Run API |
| --- | --- | --- |
| Who starts work? | An existing Hermes agent | An authenticated HTTP event |
| Preset / option selection | Parent agent, fixed, rules, or System One | Fixed, rules, or System One |
| Model / provider | Verified exact pair | Verified target model / provider |
| Explicit effort | Unsupported; omit it and inherit host behavior | Allowed only when verified on the target |
| Tool restriction | Nonempty fixed list within operator **and parent** permissions | Unsupported per run; use the target's permissions |

These are plugin-only capabilities. Do not add core patches, monkey patches, or
invented configuration keys to make an unsupported option appear available.

## Agent workflow

1. Establish the roles, whether selection should be fixed or dynamic, and the
   entrypoint. Ask only for missing decisions that change the configuration.
2. Inspect the intended profile's **effective** model/provider settings, installed
   plugin/lifecycle support, enabled parent toolsets, and provider fallback
   configuration using the host's supported read-only commands. Raw YAML can omit
   managed defaults. Do not dump `.env`, credentials, or full environment output.
3. Record exact operator-authorized model/provider identities and demonstrated
   capabilities. Model names and `efforts` lists are not capability discovery.
   If support or fallback behavior is unknown, keep execution unverified.
4. Copy the appropriate complete starter pair below into a private configuration
   directory outside the repository; edit the copy. Preserve existing profile
   settings and unrelated routes. Do not enable tools, change fallback settings,
   restart a gateway, or overwrite a live configuration just to pass validation.
5. Validate and inspect offline. Fix every quarantined preset, unavailable policy,
   and unavailable route. Show the expanded choices to the operator.
6. Report the proposed files, remaining placeholders, required environment-variable
   **names**, verification evidence, and any actions still needed before activation.
   Only perform live probes or activation within the user's authorized scope.

## The four layers

```text
inventory.models → preset.fields → preset.compatible_settings → policy
exact identities     constraints     permitted combinations      who selects
```

- **Inventory:** reusable model references such as `small` and `large`. Each has
  an exact `provider` and `model`. Optional `efforts` lists permitted labels; it
  does not choose an effort or prove provider support.
- **Fields:** `model` is required. It and `effort` support `fixed` or `enum`.
  `instructions` and `allowed_toolsets` support only `fixed`. Free-form model or
  effort generation is not supported.
- **Compatible settings:** named combinations covering **all enum fields**.
  Fixed fields are inherited and may be omitted from each combination. An effort
  in a combination must also appear in that model's inventory `efforts`.
- **Policy:** `preset_selector` chooses a preset; `field_resolver` chooses one of
  that preset's combinations. `subagent_policy` binds the native entrypoint;
  each webhook route binds its own `policy`.

For example, `small.efforts: [low, high]` is an allowlist. To actually select one
for a **webhook**, use `fields.effort: {mode: enum, candidates: [low, high]}` and
explicit combinations such as `routine: {model: small, effort: low}` and
`careful: {model: small, effort: high}`. The resolver chooses one whole combination.
There is no implicit first-value default. On a **native subagent**, omit the
`effort` field entirely, even if the inventory lists efforts.

## Two complete starter pairs

The linked YAML files are complete configurations, not fragments. Their model
names are placeholders and their deployment verification flags deliberately deny
execution until the real environment has been checked.

### 1. Parent-selected subagent

Copy [presets.yaml](../examples/presets.yaml) and
[deployment.yaml](../examples/deployment.yaml). The preset `analyst` offers
`routine` (small) and `complex` (large), without an explicit effort.

From a repository checkout:

```sh
mkdir -p "$HOME/.hermes/orpheus-draft"
# Run these copies only for a new draft; preserve existing files.
cp -n examples/presets.yaml "$HOME/.hermes/orpheus-draft/presets.yaml"
cp -n examples/deployment.yaml "$HOME/.hermes/orpheus-draft/deployment.yaml"
```

Replace the inventory placeholders with exact authorized identities. Keep
`verified_settings: []` and `fallback_disabled: false` until evidence establishes
support and disabled fallback. Then list only verified `{provider, model}` pairs
and record `fallback_disabled: true`. These declarations **do not change** Hermes
or disable its fallback. Do not assert them merely to bypass a launch error.

If the preset fixes `fields.allowed_toolsets`, authorize those toolsets in the
deployment's `subagent.allowed_toolsets` as well; they must also be available to
the parent. If the preset field is omitted, the child inherits host/parent tools
and the deployment list does **not** limit them. In particular, the starter's
`subagent.allowed_toolsets: []` does not mean a child has no tools.

The parent first calls `orpheus_presets` and checks `execution_capability` and
`capability_reasons`. Reasons such as `unverified_settings`, `unverified_fallback`,
and `unsupported_effort` explain blocked launches. Only the first failing check
per candidate is reported; fixing one reason can reveal another. Recheck after
each correction before spawning. With activation authorized and capability checks satisfied, it may request:

```json
{"task":"Review the supplied change.","preset_id":"analyst","proposals":{"model":"small"}}
```

This is the argument object for `orpheus_spawn`. `proposals.model` uses the
inventory reference, not the provider's model identifier. Parent proposals must
identify exactly one compatible combination. Omitting `proposals` succeeds only
when the preset has a single combination; otherwise missing or ambiguous proposals
fail. Do not propose a tuple ID or override fixed fields. After a successful spawn,
call `orpheus_status` with `{"request_id":"<returned request_id>"}` until terminal
status, and inspect the result rather than treating launch acceptance as completion.
A normal accepted spawn returns `state: running`. If it instead returns
`state: unknown` with `error: launch_outcome_unknown`, the host may already have
accepted the child: **do not spawn again or classify it as failed**. Preserve the
returned `request_id` for operator reconciliation. Orpheus has no stored handle
for that ambiguous launch, so its status/cancel tools report `unavailable`; that
is not proof that no child exists or permission to retry.

Only declared inputs are accepted. For extra context, declare e.g.
`context.operator_rules: {type: string, max_length: 4000}` in the policy's
`input_schema`, then pass `"context":{"operator_rules":"…"}`. Do not pass a
string as `context`, nested objects, or undeclared keys. Instructions such as
“read only” are behavioral guidance, not a permission sandbox. Omitted toolsets
inherit host behavior; an empty preset list is not a supported way to disable tools.

### Calling-session model

Orpheus observes the model and provider of each successful provider response
through the `post_api_request` lifecycle hook and keeps the latest observation per
session ID. `orpheus_presets` reports it for the calling session as `session`:
`provider`, `model`, `model_ref` (the inventory reference naming that exact pair,
or `null` when none or several match), `matching_refs` and `observed_at`. It is
`null` until the session has completed a model response that Orpheus observed,
for example right after the plugin is enabled.

A native policy may also declare these host-observed values as selection inputs:

```yaml
input_schema:
  task.text: {type: string, max_length: 16000, required: true, trust: payload}
  session.model_ref: {type: string, max_length: 64, trust: verified_metadata}
```

Allowed names are `session.model`, `session.provider` and `session.model_ref`.
They must be optional `string` fields with `trust: verified_metadata`, and they
are native-only. Callers cannot supply them through `context`. Rules can match
them (for example `{field: session.model_ref, op: eq, value: opus}`), and System One
receives them only when they are listed in `projection_fields`. An unknown or
out-of-bound value is omitted, so write rules with a `no_match` that is acceptable
when the session model is unknown. Orpheus never excludes or changes a candidate on
its own because of the session model. The selection result records the values it
used under `session_inputs`.

The observation is the model of the calling session's latest provider response, not
proof of who authored a given artifact: a child or another tool may have written it.

Native tasks are capped at **16000 characters**; set `task.text.max_length` no
higher. Rendered native context is capped at **32000 characters**, including the
`Preset instructions:` prefix and instructions, the `Explicit task context:`
prefix, separators, and JSON-encoded context. Leave room for all these parts and
JSON escaping: quotes, backslashes, newlines and other controls can expand when
encoded. Per-field bounds alone do not guarantee that the combined context fits;
check the actual rendered size before calling spawn. The native size check occurs
after resolution, so oversized input can fail with `input_too_large` after a paid
System One selection has already occurred.

### 2. Fixed webhook preset, rule-selected model and effort

Copy [webhook-presets.yaml](../examples/webhook-presets.yaml) and
[webhook-deployment.yaml](../examples/webhook-deployment.yaml). They define:

- `POST /orpheus/webhooks/issue-analysis` with a fixed `analyst` preset.
- JSON body `{"kind":"routine","title":"Example","description":"Task text"}`.
  All three fields are required; `kind` also accepts `complex`.
- `routine` → small / low, `complex` → large / high. Unknown values are rejected.
- A separate HMAC secret, target API token, and scoped operator token, referenced
  only by environment-variable name.

```sh
cp -n examples/webhook-presets.yaml "$HOME/.hermes/orpheus-draft/webhook-presets.yaml"
cp -n examples/webhook-deployment.yaml "$HOME/.hermes/orpheus-draft/webhook-deployment.yaml"
```

Create the private draft directory first if starting with this pair. Replace both
inventory identities and the deployment target's `models` mapping consistently.
The mapping keys are actual model names, not inventory references. `url` is the
Run API origin/base URL, without `/v1/runs`; use HTTPS. For local tests only,
a loopback HTTP target needs `allow_loopback_http: true` on that target. Set a stable `principal` for the target profile and
credential scope. Leave `verified: false` and `fallback_disabled: false` until
that target has demonstrated fresh-session runs, exact model/provider support,
requested effort handling, retained inherited instructions, and disabled fallback.
Do not treat a successful offline parse or HTTP acceptance as that evidence.

Route preset selection belongs in the bound policy, not the request body. To
create a dedicated reviewer route, give it a unique ID/path, bind a policy whose
selector is `kind: fixed, preset: reviewer`, and configure a unique stable security
scope. If reusing an `auth_profile` for a second route, give that route a distinct
`security_scope`; alternatively use a separate auth profile with a distinct
`scope`. Add the new scope to the appropriate token's list under deployment
`operators` so authorized operators can inspect/cancel its runs. The actual path is always `/orpheus/webhooks/<id>`; an optional `path` must
match. Payload values are untrusted even after authentication; never use a body
claim as the caller's identity or let it overwrite deployment settings.

The sender signs the **exact raw JSON bytes** with HMAC-SHA256 and supplies
`X-Hub-Signature-256: sha256=<hex digest>` plus `Content-Type: application/json`.
Operator requests use a separate bearer token authorized for the route scope;
the target API token is separate again. Preserve scopes across key rotation.
Repeated identical raw bodies within a scope return the existing request;
raw-body digests are retained indefinitely, so even distinct legitimate events
with identical bodies collapse. Distinct events must differ in signed body bytes
(for example, include a unique event ID in the JSON body); unsigned delivery-ID
headers do not distinguish them. Receipt support is currently
`{kind: disabled}` only. Do not replace a production native webhook that has
receipt hooks or other behavior without explicitly accounting for that behavior.

## Choose the resolver

Both selectors use an `id`, `kind`, and optional `on_error` list. Use unique node
IDs within a policy. Start with `on_error: []`; failures stop selection rather
than silently changing models.

| Kind | Preset selection | Field selection |
| --- | --- | --- |
| `fixed` | `preset: analyst` | `settings: routine` |
| `parent` | Caller supplies `preset_id` | Caller supplies field `proposals` |
| `rules` | Matching rule returns `preset` | Matching rule returns `settings` |
| `systemone` | Chooses among configured presets | Chooses among the selected preset's combinations |

`parent` is native-only. For other kinds, callers must omit the corresponding
`preset_id` or `proposals` argument entirely; even `proposals: {}` is forbidden
when the field resolver is not `parent`.

Rules run in ascending unique integer `priority` order and stop on the first
match. Predicates support `eq`, `in`, `contains`, `exists`, and `all`/`any`/`not`.
`no_match: {kind: error}` rejects unmatched input. Webhook rule fields must be
listed in `routing_fields` on **every route bound to that policy**. Fixed or
rule-selected setting IDs must exist in **every reachable preset**, so use common
tuple names or separate policies. A `parent` or `systemone` preset selector makes
every valid preset in the registry reachable, including newly added presets.

For System One, start from the complete
[systemone-presets.yaml](../examples/systemone-presets.yaml). It keeps parent
preset selection but lets System One select the model. The selection model is
separate from the model that will execute the task:

```yaml
field_resolver:
  id: fields
  kind: systemone
  model: typesafe/jev-1.14
  projection_fields: [task.text]
  required_fields: [task.text]
  timeout: 10
  retries: 1
  on_error: []
```

For OpenRouter, set these **deployment** keys together:

```yaml
systemone_endpoint: https://openrouter.ai/api/v1/systemone
systemone_token_env: OPENROUTER_API_KEY
```

These blocks replace the corresponding fields; they are not standalone files.
The endpoint is the full System One HTTPS endpoint, not a chat-completions URL.
The default is `https://api.typesafe.ai/v1/systemone` with `TYPESAFE_API_KEY`.
Setting only `systemone_token_env` (or legacy `jev_token_env`) keeps that default
endpoint and sends the named credential to Typesafe. Always change both endpoint
and token-environment keys together for another provider. Use endpoint-appropriate
credentials; never send an OpenRouter token to the Typesafe default. Secrets belong
in the process environment, not YAML or Git.
`jev`, `jev_endpoint`, and `jev_token_env` are legacy compatibility aliases; write
new configurations with the canonical System One names and do not mix aliases.

Only explicitly projected inputs are sent as System One state. For webhooks,
projections must also be in `routing_fields` or `task_fields`; replace `task.text`
with the route's declared names. Offline validation does not catch a projection
that is declared in `event_schema` but absent from both route lists: runtime drops
it, or rejects selection if it is also a `required_fields` entry. Check both lists.
Preset and tuple IDs, preset descriptions, and candidate settings are also sent,
so keep secrets out of IDs, purpose, guidance, instructions, and task data.
Each selection stage supports at most 255 choices. Timeout/retry bounds do not
make selection offline: live System One resolution makes external API calls.

## Validate before activation

With Orpheus installed in your Python environment, run from the checkout (or use
absolute paths to your private drafts). `python -m orpheus.cli` below and the
installed `orpheus` console command are equivalent; `uv run orpheus` in the README
runs that console command in the project's managed environment:

```sh
python -m orpheus.cli validate examples/presets.yaml --deployment examples/deployment.yaml
python -m orpheus.cli inspect examples/presets.yaml --deployment examples/deployment.yaml --entrypoint subagent
python -m orpheus.cli validate examples/webhook-presets.yaml --deployment examples/webhook-deployment.yaml
python -m orpheus.cli inspect examples/webhook-presets.yaml --deployment examples/webhook-deployment.yaml --entrypoint webhook
```

These commands make no provider calls and need no credentials. Expect exit code
0, empty `quarantined`, `unavailable_policies`, and `unavailable_routes` mappings,
and the intended `expanded_settings` in inspection output. `capability_status:
unverified` is expected: offline validation proves structure, not connectivity,
authorization, provider support, or effective execution settings. It also does
not catch native-incompatible effort fields, missing deployment tool permissions,
or unverified model/provider pairs. Use native `orpheus_presets` capability reasons
for those checks before an authorized live spawn.

On exit 1, correct the actual source problem (unknown key/reference, invalid
combination, duplicate YAML key, bad route/deployment reference); rerun both
commands. Per-preset errors appear under `quarantined`, and compiled policy errors
under `unavailable_policies`. `unavailable_routes` covers routes whose bound policy
is unavailable. Invalid route structure, bindings, deployment keys, or references
instead fail at the top level, often with no source location: for example,
`{"valid":false,"error":"invalid_config"}` or a specific deployment error code.
Deployment YAML syntax errors report `source_unavailable`; duplicate keys report
`invalid_config`. Compare the failing draft with its valid starter and inspect
changed keys/references rather than assuming the diagnostic identifies a line.
Do not hide errors by dropping intended presets, weakening constraints,
or inventing verified capabilities. Avoid printing inspection output if someone
has mistakenly placed sensitive text in instructions; remove that data first.

Hand back the complete draft pair, a short explanation of each selection path,
offline command results, and an activation plan naming the remaining host checks.
For live verification, distinguish **resolved selection**, **launch acceptance**,
and **observed runtime/result**. Only claim what the available evidence proves.
