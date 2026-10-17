# Configuration interface simplification proposal

Status: alternative for discussion, 2026-10-17. This does not replace the Claude-reviewed design or inherit its approval. It changes the proposed authoring interface, not Hermes runtime capabilities. The current design is coherent but exposes too many compiler concepts to preset authors.

## Recommendation

Make a preset the primary authoring unit. Put allowed models and their allowed effort values together. Derive compatible execution choices internally; do not require inventory, field modes and named complete tuples to repeat the same constraints. Keep entrypoint selection policy administrator-bound outside the preset.

```yaml
presets:
  analyst:
    description: Analyze a task and explain the evidence.
    instructions: Explain conclusions and identify uncertainty.
    models:
      - provider: authorized-provider
        model: configured-small-model
        effort: [low, high]
      - provider: authorized-provider
        model: configured-large-model
        effort: high

entrypoints:
  subagent:
    presets: [analyst]
    select: parent
  webhooks:
    issue-analysis:
      presets: [analyst]
      select: jev
      auth: issue-source
      target: primary-api
      input: issue-event
```

This is an illustrative authoring fragment, not installed-plugin syntax or a complete deployment. `auth`, `target`, and `input` reference separately configured authentication, execution-target and typed extraction settings. Jev also needs administrator-managed credentials, model/version and disclosure configuration. Hiding these details from a preset example does not remove their validation or replay/authentication requirements.

## Exact selection semantics

- `models` is the preset's nonempty allowed candidate list, not a declaration that a provider is installed or that its model supports those values. Validate every candidate against deployment capabilities; do not silently remove unsupported choices.
- A scalar `effort: high` fixes effort for that model candidate. A nonempty list `effort: [low, high]` permits either value. List order is not preference, priority or fallback order. A singleton list has the same candidate set as a scalar.
- The example compiles to three choices: `(small, low)`, `(small, high)`, `(large, high)`. No cross-product combines one model's efforts with another's. Canonical provider/model/effort values produce internal stable choice IDs and a pinned candidate revision.
- Reject duplicate provider/model entries, duplicate effort values and unknown fields instead of merging ambiguous definitions. Optional shared aliases can be considered later if actual reuse warrants another concept; they are not mandatory in the first interface.
- Omitted effort explicitly means native inheritance, advertised as such. It is never interpreted as low, high, or automatic selection and does not meet dynamic-effort requirements. If an entrypoint cannot preserve or verify inheritance it reports incompatibility. Any declared effort still requires the existing enforcement gate.
- One allowed preset fixes preset identity. Multiple allowed presets permit selection among that entrypoint's list. Likewise one execution choice requires no model/effort decision. Zero choices are invalid. Skip selector inference when the entire request has exactly one choice.
- `select: parent` lets the existing parent provide preset/model/effort proposals; every value must resolve to an allowed choice. This is available only to the subagent entrypoint. The parent cannot choose or change the configured policy.
- `select: jev` selects an allowed `(preset, provider, model, effort)` choice in one bounded Choice operation, using preset descriptions and configured routing context. Preserve the 255-candidate limit: reject an oversized candidate set rather than truncate or silently stage it. Model-specific hints may be added as an optional candidate description when necessary.
- `select: rules` evaluates the already-defined typed predicates. A rule's result identifies a preset/provider/model/effort directly; named tuples are not required. Omitted result fields may be filled only when the remaining allowed candidate set contains exactly one choice. Zero or multiple choices is a visible routing error. Compile static rule results against the allowed candidates, and validate again before launch.
- Webhooks accept only rules/Jev selection. No-match defaults to an error; no implicit LLM fallback. If a fixed binding leaves exactly one complete choice, no resolver call is needed.

For example, a rule selecting only `small` with two allowed efforts is incomplete and fails. A rule selecting `small` plus `high` is complete. A parent or Jev may choose either small-model effort based on task context; the list itself does not instruct which one to prefer.

## What becomes internal or advanced

| Current authoring concept | Proposed treatment |
|---|---|
| Mandatory `inventory.models` | Inline candidates in each preset; optional reuse mechanism only if needed later. |
| `fields.model/effort.mode` and `candidates` | Model list plus scalar/list effort syntax. |
| Mandatory `compatible_settings` | Compiler derives valid choices from each model's own effort declaration. |
| Separate selector/resolver IDs for basic use | One `select` per entrypoint covering every unresolved choice. |
| Mixed preset-selection and field-resolution engines | Advanced extension, deferred from the minimal interface; not silently approximated. |
| Fallback graphs and named resolver nodes | Advanced policy configuration, with explicit failures as the simple default. |
| Typed extraction, authentication, deduplication and target authority | Retain in administrator ingress configuration; do not expose as preset fields. |

The concise interface trades some advanced flexibility for fewer concepts. If a deployment must use parent preset choice but Jev effort choice, it needs an explicit advanced policy extension; the basic `select` form cannot express that. Free generation remains a separate future subagent-only design choice, not implied by an omitted list or an `auto` string. Runtime effort limitations remain unchanged.

## Adoption work

If adopted, replace the authoring/configuration parts of the requirements and design, define the normalized compiler representation and parser schema, add validation cases for all semantics above, and rerun Claude review. Keep existing security, lifecycle, snapshot and capability invariants. The old review remains valid only for its recorded document hashes.
