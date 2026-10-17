# Claude final review — fixed-preset webhook smoke

Requested claude-opus-5-5 high; reported ['claude-opus-5-5']; exit 0. Fresh no-tools narrow review. Earlier round supplies accepted runtime/harness/evidence coverage, bound by hashes. The README excerpt in this narrow packet intentionally omitted unrelated lines; the actual file retains intact paragraphs (checked locally).

**APPROVE**

The prior blocker is resolved. The fixed function has no remaining false-pass path that I can find.

**Corrupt path**
- `pytest.raises(AssertionError)` now wraps only `await probe.run(...)`. The two postchecks run outside it, so a failure in either one fails the test.
- If the server-side header assertions in `submit` fail, aiohttp turns that into a 500 response. In that case `calls.append` never runs, so `len(calls) == 1` fails. A probe error caused by the 500 can no longer pass as the expected refusal.
- `'payload-override' in calls[0]['instructions']` shows the corrupted payload actually reached the server. `len(calls) == 1` shows the probe stopped after the first submission.
- If `altered` itself fails, it raises KeyError or TypeError, not AssertionError, so the test fails rather than passing falsely.
- The uncorrupted case uses the same server and passes. The only difference is the instruction mutation, so the refusal is attributable to it.

**Clean path**
- `report` is produced inside `async with`, and the assertions run afterward with `calls` still in scope.
- If a handler assertion fails, `probe.run` raises without being caught, so the test fails.
- No assertion is wrapped by an exception handler.

**Optional hardening (P3, non-blocking):** add `match=` to `pytest.raises`, keyed to the probe's exact-payload mismatch message. That would tie the refusal to the specific check rather than relying on the control comparison.

**Qualification**
- The metadata is consistent with the stated scope. It keeps the test hash from the live run, records the current hash for the test-only correction, and says the live probe does not import the unit test.
- Caveat on the pasted README paragraph: the lines are not contiguous. For example, "passed against a separately" runs straight into "or restarted." I assumed this is elision in your excerpt. If the file actually reads that way, it is a P2 documentation defect to fix before publishing.

**Scope of this review**
- I used no tools. I did not verify the stated unchanged SHA256 values, the 120 tests / 57 subtests PASS result, or any test execution.
- I inherited the prior round's accepted coverage of the runtime, harness, and bootstrap source without re-reviewing it.
