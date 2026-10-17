# Actual local Hermes fixed-preset webhook smoke

On 2026-10-17, `tests/live/webhook_preset_smoke.py` passed against a separately
started API adapter from the user's installed local Hermes runtime. The operator
observed a clean Hermes checkout; the probe itself does not check Git state.
The probe used actual signed HTTP requests into Orpheus and actual authenticated
`POST /v1/runs` / run-status calls into Hermes. Both runs performed real model
inference. The requested and native-reported final runtime pair was
`claude-subscription-directsdk-experimental` / `claude-opus-5-5[1m]`. No mock host or model was used for this
receipt.

The operator-started adapter used the existing profile credentials, random temporary
API authentication, and an ephemeral loopback port. The effective gateway fallback
chain was checked empty before the probe. The full existing gateway was not started
or restarted. Orpheus ingress was mounted separately by the test harness; this test
does not claim to exercise plugin discovery or mounting into a running gateway.

Results in `receipt.json`:

- `/orpheus/webhooks/reviewer` selected the fixed `reviewer` preset.
- `/orpheus/webhooks/auditor` selected the fixed `auditor` preset.
- Both completed with distinct native run-scoped session IDs and returned their preset-specific
  instruction marker plus the correct discount boundary defect (`10000 -> 9000`,
  operator `>=`). The markers were supplied only by preset instructions.
- Exact launch payloads matched configured model/provider/instructions and contained
  no session/history reuse field. Payload-supplied preset/model/instructions/effort
  overrides were ignored because they were not extracted into the route schema.
- One unsigned request to `reviewer` was rejected before dispatch; unauthenticated operator status
  was forbidden. Replaying each signed body returned its original request. Exactly
  two upstream submissions occurred across both routes.

`operator-metadata.json` binds the receipt to the harness/product source hashes and
installed Hermes revision. Raw runtime logs and ephemeral authentication files are
kept outside Git. No secret values are part of the public fixture or receipt.
The metadata separately records a later unit-test-only correction that narrowed an
expected-failure assertion; the actual live harness and runtime files are unchanged.
`bootstrap-receipt.json` records completion of the adapter cleanup code and equal
before/after fingerprints for five protected paths. A missing path fingerprints as
null, so this is not proof that all five files existed. Successful process exit and
connection-file removal were separately observed by the operator, not independently
proved by the bootstrap receipt. The metadata sidecar records those operator
observations and hashes this receipt.

This verifies fixed administrator route binding, not payload-controlled arbitrary
preset selection. It makes no Jev selection call and requests no explicit effort.
Hermes reported the expected final model/provider pair; that is native final-runtime
metadata, not provider wire-level observation. The tool-free review instruction is
not a permission-isolation claim. Existing profile sessions created by this probe
remain as normal local Hermes history. Distinct run-scoped IDs and omitted reuse
fields support normal fresh-run semantics; no independent history inspection proved
that prior context was absent.
