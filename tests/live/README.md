# Local reviewer-preset smoke test

These fixtures do not install plugins, configure Hermes, or invoke a model.
The operator must first install Orpheus in the real Hermes Python environment,
configure a `reviewer` preset with a fixed authorized model/provider and no effort
override, disable provider fallback, and verify those deployment settings.

Submit `review_prompt.txt` through the public Hermes CLI in a new session.
The prompt delegates exactly one read-only review using Orpheus. The defect in
`discount_fixture.py` is deterministic: 10,000 cents currently returns 10,000;
the contract requires 9,000. No project files or secrets are needed by the child.
Tool-free review is a task instruction, not a claim of permission isolation;
stock Hermes does not interpret an empty allowed-toolset list as zero tools.

After the parent completes, export only that session through the public CLI:

```sh
hermes sessions export /private/tmp/orpheus-review-session.jsonl --format jsonl --session-id SESSION_ID --redact
python tests/live/verify_review_export.py /private/tmp/orpheus-review-session.jsonl --session-id SESSION_ID
```

Installed source inspected on 2026-10-17: `hermes_cli/subcommands/sessions.py`
defines the export flags; `hermes_cli/session_export.py` and
`hermes_state_portability.py` establish one session object with a `messages`
array per JSONL line. Keep raw exports outside the repository because inherited
session metadata may contain private information. Save only reviewed/redacted
verification receipts as evidence.

The verifier requires actual assistant tool-call IDs linked to tool-role JSON
responses, discovery before spawn, a matching spawn/status request ID, native
SUCCEEDED, ready child output, and the correct boundary-case review finding.
Final assistant statements alone cannot pass. This verifies delegation and the
returned result; effective provider settings need separate request-level proof.
