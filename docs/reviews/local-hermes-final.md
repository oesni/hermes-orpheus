# Claude review — native directory install and live verification

Requested claude-opus-5-5; reported ['claude-opus-5-5']; exit 0. Source review only.

**Verdict: APPROVE.** None of the changes has a material defect. I reviewed only the text you supplied, so this is source review. I did not run the tests or the verifier, and the live run and the 101 passing tests are your results, not something I reproduced.

## How the earlier findings were handled

1. **The dependency contradiction is fixed.** Both READMEs now say that `hermes plugins enable` installs the declared dependencies and that manifest parsing only checks them. This matches what you confirmed in the installed source.
2. **The receipt labelling is fixed.** The verifier output and the `operator_metadata` fields are now clearly separate.
3. **The hash field is fixed.** It is now `redacted_export_sha256`, and the README says it is not the hash of the raw stream.
4. **The directory-plugin test is fixed.** The environment variables now point at missing paths inside the temporary directory, and the test checks that the fake `HERMES_HOME` is never created.
5. **Malformed input now fails cleanly.** Bad tool-call and preset entries are type-checked, and `main()` also catches `OSError`. The CLI test checks that the output is a JSON failure and that nothing goes to stderr. In the code you supplied, I found no remaining way for malformed input to escape as a traceback.
6. **The install steps are fixed.** They now refuse an existing destination, so copying cannot leave stale modules behind.
7. **The usable check is added.** The reviewer preset must report `execution_capability == 'compatible'` and an empty `capability_reasons` list.
8. **`__all__` is fixed.** It is now set correctly in both branches.

## Minor points (not blocking)

- **The receipt may predate the stricter verifier.** The reviewer check (and the stricter type checks) were added after the live run. The README describes `receipt.json` as verifier output, but nothing ties the receipt to the final verifier. Run the final `verify_review_export.py` against the private redacted export again and confirm the output matches `receipt.json`. Ideally, also record the verifier's SHA-256 in `operator_metadata`. Until then, the receipt shows what an earlier version of the verifier accepted.
- **The README points to an upgrade procedure that doesn't exist.** The install snippet says "use an upgrade procedure instead", but no upgrade procedure is written down. Add a short one, for example: remove the old directory and copy again. Also, `cp -R orpheus` will copy any local `__pycache__` folders; this is harmless.
- **Part of the test runs outside the environment patch.** The `orpheus_presets` handler is called after `patch.dict` has ended. If the plugin reads configuration lazily when a tool is called rather than at registration, the host's environment could still affect the result. Moving the handler call inside the `with` block would close this.
- **The task check only matches a substring.** `'discounted_total' in args.get('task', '')` is enough, because a correct child finding is also required. I'm noting it only for completeness.
