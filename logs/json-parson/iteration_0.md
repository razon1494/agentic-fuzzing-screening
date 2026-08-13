# Iteration 0

- strategy: `iteration_0.py`
- cost: $0.2453

## Rationale

The generator mirrors the ANTLR grammar's rule structure directly: json_string/json_number implement the STRING/NUMBER terminals (with low-probability malformed variants folded in), json_true/json_false/json_null implement the literal alternatives of `value`, and `_json_object`/`_json_array` implement `obj`/`arr` using st.recursive so that `value -> obj|arr -> value` mutual recursion is real and unbounded in principle (bounded only by Hypothesis's own size budget via max_leaves), never flattened to a fixed depth. Every recursive production (`obj`, `arr`, `value`, `json`) is wrapped in the `production()` context manager: every terminal production (`STRING`, `NUMBER`, `true`, `false`, `null`, `pair`) calls `record_production`, using the grammar's own names so coverage output lines up with the grammar text. Most generated documents are still fully grammar-conformant JSON (empty/non-empty objects and arrays, all literal kinds, escaped and unicode strings, well-formed numbers with optional fraction/exponent) so the parser's mainline paths dominate. A minority of documents intentionally reach past or short of the strict grammar per the measured contract: single trailing commas in objects/arrays, a UTF-8 BOM prefix, trailing garbage/comment-shaped text after the first value, an embedded NUL, lone surrogate escapes, duplicate object keys, malformed numbers (trailing dot, huge exponent, leading zero, leading plus), raw high-byte string content via surrogate-escape codepoints, and an explicit deep-nesting probe sampled around parson's measured 2048/2049 wall. These are all kept as low-probability branches so the overall corpus is still mostly accepted by the parser rather than rejected at the tokenizer.

## Measured results

```
examples=500  accept=225, reject=275
acceptance_rate=45.0%
unique_crash_signatures=0
productions_exercised=['NUMBER', 'STRING', 'arr', 'false', 'json', 'null', 'obj', 'pair', 'true', 'value']
depth_histogram=d1:13, d2:31, d3:104, d4:151, d5:119, d6:61, d7:20, d8:1
acceptance_verdict: 45.0% -- healthy: a real mix of accepted and rejected inputs.
productions_never_exercised: none
depth_verdict: max depth 8, with a real spread across depths
productions_recorded_under_unrecognized_names: ['json'] (use the grammar's own rule names so coverage lines up)

no crashes yet
```
