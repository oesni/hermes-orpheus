# Proposed Hermes per-launch settings extension

This companion patch is **not submitted upstream, installed, or deployed**. It targets only Hermes commit `7e9eb8d9a30f4a9bb9f8ecaf816b4b0ffdf47357`. Original files under `upstream/` are public Hermes source fixtures with their MIT license; hashes and repository identity are in `source-manifest.json`.

The public lifecycle adds optional `reasoning_effort: str | None` and exact boolean `disable_fallback`. `capabilities()` advertises their construction contract as `per-launch-v1`. The request validator uses Hermes's canonical effort parser: recognized effort strings and disabled aliases are accepted; non-string values and unknown names fail. The child builder repeats validation, parses into a fresh reasoning dictionary, and overrides the per-child runtime before constructing `AIAgent`. `disable_fallback=True` sets the existing singular `fallback_model` constructor option to `None`. Omitted fields preserve legacy parent/delegation behavior. The existing parent-tool-preserving wrapper already forwards keyword arguments and needs no patch.

The marker proves only the public constructor contract. It does not prove a particular provider honors effort, disables its own remote routing, or reports every effective request. Orpheus deployment capability evidence remains mandatory. There is no private mutation, runtime monkey patch, global reasoning swap, or matching by task text.

Run offline verification from this repository:

```sh
python compat/verify_patch.py
python -m pytest tests/test_hermes_patch.py -q
```

Optional public network provenance verification (downloads only, never modifies a host installation):

```sh
python compat/verify_patch.py --verify-remote
```

Verification checks source hashes, clean `git apply --check`, patch application in a temporary directory, and compilation of all fixture modules. Tests execute the actual patched AST functions for launch, the preserving wrapper, child construction and canonical effort parsing with non-provider dependencies stubbed. They prove forwarding before first constructor invocation, simultaneous identical-task isolation, absence preserving defaults, invalid-input rejection, fallback suppression and capability detection. They are not a live provider integration test or a complete Hermes regression suite. An upstream PR and live deployment acceptance remain separate actions.
