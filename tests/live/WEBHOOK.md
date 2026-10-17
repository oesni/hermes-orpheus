# Fixed-preset webhook probe

`webhook_preset_smoke.py` mounts the production Orpheus `WebhookService` on an
ephemeral loopback listener and uses the production registry, resolver, ledger,
and authenticated HTTP `RunClient`. It submits two synthetic review tasks to an
operator-supplied isolated Hermes Run API. This is an opt-in model-using probe,
not part of normal pytest execution. It does not install configuration or restart
an existing gateway.

The operator must first verify the target's effective provider/model and disabled
fallback, start a separate authenticated loopback API using the installed Hermes
runtime, and place its temporary API credential in the named environment variable.
The `--verified-isolated-target` switch acknowledges those prerequisites; the
harness does not discover credentials or automatically verify provider fallback.
Optimized Python (`-O`, `-OO`, or `PYTHONOPTIMIZE`) is rejected because this
verification harness uses assertions.

```sh
python tests/live/webhook_preset_smoke.py \
  --url http://127.0.0.1:PORT --token-env ORPHEUS_TEST_HOST_TOKEN \
  --model YOUR_CONFIGURED_MODEL --provider YOUR_CONFIGURED_PROVIDER \
  --verified-isolated-target --output /private/tmp/webhook-preset-receipt.json
```

The two routes `/orpheus/webhooks/reviewer` and `/orpheus/webhooks/auditor` bind
their presets in administrator configuration:

```yaml
preset_selector: {id: reviewer-preset, kind: fixed, preset: reviewer}
field_resolver: {id: reviewer-fields, kind: fixed, settings: review}
```

The route's `policy` chooses that policy. The sender cannot choose an arbitrary
preset by putting `preset_id` in JSON: the probe sends conflicting preset, model,
instructions, and effort fields and proves none changes the exact launch payload.
Identical signed payloads sent to distinct route security scopes launch separate
runs; replaying one route's exact body reuses its existing request.

The probe also checks unsigned delivery rejection, operator endpoint authentication,
distinct host run IDs and run-scoped session IDs, omitted session/history reuse
fields, completed output, and the correct 10,000-cent
boundary finding with each preset's unique instruction marker. Preset selection is
fixed and makes no LLM/Jev selection call. Model execution uses the API target.

The model is instructed to avoid tools; that is not a tool-permission sandbox.
No explicit effort is requested. Native status `runtime` is final provider/model
metadata, not provider wire-level evidence or proof of effective effort.

Normal pytest uses a deterministic fake upstream HTTP server to validate the same
harness; only a separately recorded live receipt establishes actual Hermes/model
execution. Keep private API connection files and raw runtime logs outside Git.
