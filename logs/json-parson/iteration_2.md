# Iteration 2

- strategy: `iteration_2.py`
- cost: $0.1677

## Rationale

The grammar's mutual recursion (value <-> obj/arr) is implemented with st.recursive over composite obj/arr strategies that each enter the 'obj'/'arr' production context manager, with terminals (STRING, NUMBER, true, false, null) recorded via record_production. Superset behaviours parson actually accepts (trailing commas, trailing garbage, BOM, embedded NUL, bare trailing dot in numbers, raw invalid-UTF-8 bytes in strings) are woven into the normal generation path at meaningful frequency so most examples still parse. Subset-only inputs the grammar allows but parson rejects (duplicate keys, lone surrogates, huge exponents) appear at low frequency to exercise the error path without dominating the corpus. Two dedicated nesting strategies build depth via a loop that opens one production('arr'/'obj') context per level through contextlib.ExitStack, so the coverage harness's depth tracker sees the true structural depth: one strategy fills in moderate depths (10-800) on every run, and another brackets parson's measured per-shape nesting wall (arrays ~2045-2052, objects ~2044-2051) to test both sides of the cliff.

## Changes from the previous iteration

- depth_histogram was concentrated at d1-d7 (max depth 7) despite the previous _deep_nesting probe targeting depth 2000-2055 -- because that probe built its string with a plain loop and entered the production() context manager only once for the whole document, so the harness recorded it as depth 1, not 2000+. Rewrote _deep_nesting to use contextlib.ExitStack, entering production('arr') or production('obj')/record_production('pair') once per nesting level, so real depth is visible to the harness.
- Added a new _moderate_nesting strategy (depth 10-800, same ExitStack-per-level technique) invoked on 8% of documents, to fill in the depth histogram between the shallow recursive value strategy (previously topping out around depth 5-7) and the extreme 2000+ wall probe -- addresses 'depth histogram concentrated at 0-1'-style guidance by giving guaranteed mid-depth signal every run instead of relying on rare extreme rolls.
- Reduced container branching factor in _json_object/_json_array from 0-6 children to 0-3, and raised st.recursive's max_leaves from 90 to 150, so the leaf budget for the ordinary recursive value strategy is spent more on depth than on breadth (previous run's normal recursion never got past depth 7 even with max_leaves=90).
- Split parson's per-shape measured nesting wall more precisely: arrays bracketed at 2045-2052 (accept up to 2049, reject at 2050) and objects at 2044-2051 (accept up to 2048, reject at 2049), instead of one shared 2000-2055 range for both shapes, so probes land closer to each shape's actual boundary.
- Kept acceptance rate composition (BOM/trailing-garbage/comment/NUL/malformed-number/duplicate-key/surrogate ratios) essentially unchanged since the measured 40.2% acceptance rate was reported as healthy and productions_never_exercised was already 'none' -- no correctness fix needed there, only re-numbered the roll thresholds to make room for the new moderate-nesting slice.

## Measured results

```
examples=500  accept=293, reject=207
acceptance_rate=58.6%
unique_crash_signatures=0
productions_exercised=['NUMBER', 'STRING', 'arr', 'false', 'null', 'obj', 'pair', 'true', 'value']
depth_histogram=d1:27, d2:111, d3:161, d4:56, d5:71, d6:31, d7:7, d8:1, d10:9, d11:1, d124:1, d188:1, d192:1, d280:1, d286:1, d362:1, d385:1, d576:2, d633:1, d787:1, d2044:2, d2045:7, d2049:2, d2050:1, d2051:2
acceptance_verdict: 58.6% -- healthy: a real mix of accepted and rejected inputs.
productions_never_exercised: none
depth_verdict: max depth 2051, with a real spread across depths

no crashes yet
```
