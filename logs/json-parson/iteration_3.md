# Iteration 3

- strategy: `iteration_3.py`
- cost: $0.1534

## Rationale

The previous iteration's measured run showed a healthy 58.6% acceptance rate, full production coverage, and a genuine depth spread up to 2051, with no crashes. Rather than restructure what is already working, this revision targets the specific measured gap-table rows the previous generator could not reach: nested duplicate keys (only adjacent same-object reuse was possible before), the double-trailing-comma subset-agreement case ([1,,] / {"a":1,,}), and the genuine `/* */` comment-inside-value rejection (as opposed to the tolerated trailing `// hi` garbage, which was already covered). The raw-invalid-UTF-8-in-string path and the near-wall nesting probe are bumped slightly since the writeup flags the former as under-tested and the latter's previous 4% sample (~20 of 500) is thin for pinpointing exact boundary behaviour. All recursion is still expressed through st.recursive/composite with production() context managers entered once per nesting level, so the coverage harness's depth tracking remains accurate as verified last run.

## Changes from the previous iteration

- Added `_nested_duplicate_key` strategy and wired it into json_document at 4% (roll<18) to generate `{"x":{"a":1,"a":2}}`-shaped inputs -- the table explicitly says the duplicate-key reject 'also holds nested', which the old adjacent-reuse-only mechanism inside `_json_object` could never produce.
- Added a double-trailing-comma branch (`,,`) at 3% inside both `_json_object` and `_json_array`, alongside the existing single-trailing-comma branch, to exercise the documented agreement case '[1,,]' / double trailing comma is rejected by both grammar and parson -- previously untested.
- Added a genuine `/* hi */` block-comment suffix branch (4%, roll<47) in `json_document`, distinct from the existing tolerated `// hi` trailing-garbage branch, to test the documented subset row that `{"a":1 /* hi */}`-style in-value comments are rejected by the non-comment entry point.
- Bumped the raw invalid-UTF-8-in-string branch of `json_string` from mode<100 (8%, i.e. 92-99) to mode>=89 (11%) since the writeup calls this 'a genuinely under-tested surface'.
- Bumped the near-wall `_deep_nesting` probe from 4% to 6% (roll<6) since the previous run's ~20-example sample at the exact 2048/2049/2050 boundary is thin for a boundary this precise and it is the most promising unexplored region for a crash.
- Left the core recursive value/obj/arr structure, production()/record_production() instrumentation, and ExitStack-based per-level nesting unchanged since the measured depth histogram (max depth 2051, real spread) and full production coverage confirmed they already work correctly.

## Measured results

```
examples=500  accept=266, reject=234
acceptance_rate=53.2%
unique_crash_signatures=0
productions_exercised=['NUMBER', 'STRING', 'arr', 'false', 'null', 'obj', 'pair', 'true', 'value']
depth_histogram=d1:29, d2:115, d3:150, d4:104, d5:37, d6:27, d7:1, d8:1, d10:6, d11:1, d12:2, d72:1, d158:1, d198:1, d265:1, d319:1, d360:1, d372:1, d500:1, d583:1, d2044:4, d2045:5, d2047:2, d2048:3, d2050:1, d2051:3
acceptance_verdict: 53.2% -- healthy: a real mix of accepted and rejected inputs.
productions_never_exercised: none
depth_verdict: max depth 2051, with a real spread across depths

no crashes yet
```
