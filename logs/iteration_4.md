# Iteration 4

- strategy: `iteration_4.py`
- cost: $0.1906

## Rationale

The strategy mirrors JSON.g4's mutual recursion (value <-> obj/arr) via st.recursive over a base of STRING/NUMBER/true/false/null and a container extension, with every recursive production wrapped in production() and every terminal recorded via record_production(), matching the grammar's own rule names. On top of grammar-conformant output it deliberately injects the measured disagreements: trailing commas (accepted), double trailing commas (rejected), trailing garbage/BOM/embedded-NUL (accepted, API-boundary quirks), a genuine block comment (rejected), malformed numbers like trailing '.' (accepted) vs leading zero/plus (rejected) vs huge exponents (rejected), lone surrogate escapes (rejected), raw invalid UTF-8 bytes of several distinct malformed classes (accepted at the byte level), adjacent and nested duplicate keys (rejected), and nesting depths sampled precisely around parson's measured MAX_NESTING wall for both pure-array, pure-object, and now alternating array/object shapes, since the wall sits one level apart between the two pure shapes and only an alternating path can exercise both counter-increment sites in one document.

## Changes from the previous iteration

- Depth histogram had zero examples at d2046, d2049, d2052 despite the walls sitting at array 2049/2050 and object 2048/2049 -- replaced the broad st.integers wall-probe ranges with st.sampled_from over the exact bracketing depths per shape so every value on both sides of each cliff gets real weight.
- No crash signatures found yet and the writeup explicitly attributes the one-level gap between the array wall (2049) and object wall (2048) to the counter incrementing at a different point on the two production paths -- added a new _mixed_deep_nesting strategy that alternates '[' and '{' per level near the wall (2044-2051) so a single document exercises both code paths, which the previous pure-single-shape probes could never do.
- The invalid-UTF-8-in-string generator was flagged in the writeup as 'genuinely under-tested' but only ever produced uniformly random high bytes -- diversified it into four distinct malformed-byte classes (random high bytes, lone continuation bytes 0x80-0xBF, invalid leading bytes like 0xC0/0xC1/0xF5-0xFF, and truncated multi-byte sequences) to broaden the byte-level surface reaching the C parser.
- Rebalanced the top-level roll thresholds (deep nesting 7%, new mixed nesting 3%, moderate nesting 8%, nested duplicate key 4%, remainder unchanged in relative proportion) to make room for the new mixed-nesting branch while keeping the overall accept/reject mix close to the previous run's healthy 53.2%.

## Measured results

```
examples=500  accept=263, reject=237
acceptance_rate=52.6%
unique_crash_signatures=0
productions_exercised=['NUMBER', 'STRING', 'arr', 'false', 'null', 'obj', 'pair', 'true', 'value']
depth_histogram=d1:33, d2:108, d3:130, d4:92, d5:70, d6:28, d7:1, d11:1, d12:1, d13:1, d14:1, d15:1, d17:1, d85:1, d105:1, d129:1, d131:1, d286:1, d341:1, d386:1, d720:1, d2044:2, d2046:3, d2047:3, d2048:7, d2049:1, d2050:6, d2051:1, d2052:1
acceptance_verdict: 52.6% -- healthy: a real mix of accepted and rejected inputs.
productions_never_exercised: none
depth_verdict: max depth 2052, with a real spread across depths

no crashes yet
```
