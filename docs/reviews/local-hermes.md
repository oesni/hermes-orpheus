# Claude review — native directory install and live verification

Requested claude-opus-5-5; reported ['claude-opus-5-5']; exit 0. Source review only.

**Verdict: approve after fixing the dependency contradiction in the docs.** I found no defects in the runtime code, the packaging or the core logic of the verifier. One documentation contradiction should be fixed before this is relied on. The rest are minor.

I reviewed only the text you supplied. I didn't execute anything, so the 98 passing tests and the live run are your results, not something I reproduced.

## Should fix

1. **The two READMEs disagree about dependency installation.**
   - The repository `README.md` says Hermes "checks these dependencies but does not automatically install them. The host runtime must already provide them."
   - `docs/evidence/local-hermes/README.md` says "The managed runtime resolves declared plugin Python dependencies through `hermes plugins enable`."

   Both can't be true for the same managed install path. An operator following the main README could install packages unnecessarily, or rely on behaviour that isn't there. Check against the installed Hermes source which one is true, then correct the other. If "resolves" only means "checks", say so explicitly.

## Minor

2. **`receipt.json` is described as "machine-verified", but some of its fields were added by hand.** The verifier only produces `verified` through `limits`. `hermes_revision`, `tested_date`, `preset_id`, `core_modified` and `raw_export_sha256` were added afterwards. Either label those fields as operator-attested, or describe the receipt as "verifier output plus operator metadata".

3. **`raw_export_sha256` is ambiguous.** The evidence README mentions both a raw stream and a redacted session export, and says both stay outside Git. The receipt doesn't say which one was hashed, and the hash can't be linked to anything readers can see. Rename the field, for example to `redacted_export_sha256`, or add a note.

4. **`test_directory_plugin.py` isn't hermetic.** `get_config` returns `None` for `config_path` and `deployment_path`, so the plugin falls back to `ORPHEUS_CONFIG` and `ORPHEUS_DEPLOYMENT` from the environment. On a machine where those are set, `response['presets'] == []` can fail. `HERMES_HOME` can affect it too. Patch these variables out with `unittest.mock.patch.dict(os.environ, ...)`.

5. **The verifier can crash in ways `main()` doesn't catch.** Two examples:
   - A `presets` entry that isn't a dict makes `p.get` raise `AttributeError`.
   - A `tool_calls` entry that isn't a dict does the same.

   `main()` only catches `ValueError`, `TypeError` and `KeyError`, so these end in a traceback instead of `{"verified": false}`. The verifier still fails closed, but the error is uglier. Add `AttributeError`, or validate the types first.

6. **The README install steps can leave stale modules on upgrade.** `cp -R orpheus "$dir/"` merges into an existing `orpheus/` directory, so modules deleted in a newer version stay behind and can still be imported. It also copies `__pycache__`. Remove the old directory first, or use `rsync -a --delete --exclude __pycache__`.

7. **The verifier doesn't check two things the prompt asks for.**
   - The prompt asks the parent to confirm `reviewer` is "usable", but the verifier only checks that the preset id exists. If `orpheus_presets` returns a usable or quarantine flag, check it.
   - The task check is only a substring match on `'discounted_total'`. That's acceptable because a correct finding is required anyway.

8. **`__init__.py` leaves `register` undefined when `__package__` is empty.** `__all__ = ['register']` is still declared, so `from <module> import *` would raise in that case. This only matters for the pytest-collection case, so it's harmless. Setting `__all__` inside the `if` would be cleaner.

## Checked and fine

- **The verifier is strict about evidence.** It requires a linked tool-call ID before counting a result, so plain assistant prose can't pass. It also checks that discovery comes before spawn, and rejects a second spawn or a request-ID mismatch. Batched bridge calls are rejected instead of guessed, and type-strict comparison keeps `True` from matching `1`.
- **The limits are stated accurately.** Effective provider settings are reported as unobserved (`observed: null`), there's no claim of tool-level permission isolation, and the scope of `--ignore-rules` is disclosed.
- **The manifest matches the registered tools,** and the test confirms submodules load from the plugin directory under the private package namespace.
