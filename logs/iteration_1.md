# Iteration 1

- strategy: `iteration_1.py`
- cost: $0.1016

## Rationale

The strategy keeps the same grammar-driven backbone (value -> obj|arr|STRING|NUMBER|true|false|null via st.recursive, so recursion depth genuinely varies instead of being fixed) and the same deliberate mix of superset/subset edge cases measured against parson (trailing commas, trailing garbage after the first value, BOM prefix, embedded NUL, invalid UTF-8 bytes inside strings, lone surrogate escapes, huge exponents, leading zeros/plus signs, near-wall deep nesting for both arrays and objects, and occasional duplicate-key objects). Every recursive production (obj, arr, value) is wrapped in production(...) and every terminal (STRING, NUMBER, true, false, null, pair) calls record_production, using exactly the grammar's own rule names so the coverage report lines up. The one structural change is dropping instrumentation of the top-level assembly step, which the harness does not recognize as a grammar production name, while still emitting the same distribution of documents underneath.

## Changes from the previous iteration

- Removed the `with production("json"):` wrapper around the top-level document assembly and stopped calling it a production at all -- the report showed `productions_recorded_under_unrecognized_names: ['json']`, meaning the harness only tracks the grammar's own rule names (obj, pair, arr, value, STRING, NUMBER, true, false, null), not a synthetic top-level 'json' label. The docstring now explains why it is deliberately uninstrumented.
- Folded the deep-nesting probe's array/object emission into `production("arr")`/`production("obj")` blocks respectively (previously it built the nested strings with no instrumentation at all), so the ~4% of documents that probe the 2048/2049 nesting wall still contribute to the arr/obj depth histogram instead of being invisible to coverage.
- Raised `st.recursive`'s `max_leaves` from 60 to 90 to push a bit more probability mass into deeper structures, since the depth histogram was heavily concentrated at depth 3-5 (d3:104, d4:151, d5:119) with only 1 example reaching depth 8; acceptance rate (45%) and the never-exercised list (none) were already healthy so no other behavioral changes were made.

## Measured results

```
examples=500  accept=201, reject=299
acceptance_rate=40.2%
unique_crash_signatures=0
productions_exercised=['NUMBER', 'STRING', 'arr', 'false', 'null', 'obj', 'pair', 'true', 'value']
depth_histogram=d1:75, d2:94, d3:69, d4:86, d5:127, d6:42, d7:7
acceptance_verdict: 40.2% -- healthy: a real mix of accepted and rejected inputs.
productions_never_exercised: none
depth_verdict: max depth 7, with a real spread across depths

no crashes yet
```
