# Iteration 0

- strategy: `iteration_0.py`
- cost: $0.3386

## Rationale

The module mirrors the grammar's shape directly: leaf value productions (string, integer, floating_point, bool_, date_time) are implemented as flat @composite strategies that record their production name; the two genuinely recursive productions (array_ and inline_table) are built with st.recursive over a shared 'children' value strategy and each wraps its body in `with production(...)` so the coverage tracker sees real, variable-depth recursion rather than a fixed unrolled depth. Keys follow simple_key/dotted_key exactly (quoted or unquoted simple keys, 2-4-part dotted keys). Tables (standard and array-of-tables), key_value, comments, and the document's expression/NL/EOF structure are assembled to match `document: expression (NL expression)* EOF` with comments optional per expression and blank/empty documents possible (matching the confirmed 'empty document is valid' behavior). Because the ADAPTATIONS notes single out unbounded recursion as the target's real, confirmed bug (stack overflow around depth ~23,000-27,000 with no grammar-level cap), two dedicated generators (deep_array_value/deep_inline_table_value) build very deep (100-30,000 level) nested arrays and inline tables directly via string concatenation, using an ExitStack of `production()` context managers so the depth is faithfully reported to the coverage/depth tracker without hitting Python's own call-stack limit. Known superset gaps (leading-zero integers, dot-only floats, raw control bytes in basic strings) and subset gaps (duplicate keys/tables, array-of-table redefined as a plain key) are included as low-probability branches so the parser sees both its accept and reject edges without those edge cases dominating the corpus, keeping the bulk of generated documents well-formed and acceptable.

## Measured results

```
examples=500  accept=31, reject=469
acceptance_rate=6.2%
unique_crash_signatures=0
productions_exercised=['array_', 'array_table', 'bool_', 'date_time', 'dotted_key', 'floating_point', 'inline_table', 'integer', 'key_value', 'string', 'table']
depth_histogram=d0:52, d1:43, d2:63, d3:110, d4:70, d5:19, d100:8, d129:5, d213:7, d264:5, d284:7, d323:7, d352:1, d448:1, d500:3, d532:1, d818:7, d959:4, d973:3, d1103:4, d1185:4, d1350:7, d1685:1, d2158:7, d2710:2, d4126:4, d5282:7, d6996:3, d8156:6, d9618:7, d9980:7, d10851:2, d15383:7, d17079:1, d21473:3, d22178:2, d22851:7, d25704:3
acceptance_verdict: 6.2% -- low. Much of the budget is spent on inputs rejected at the front door.
productions_never_exercised: none
depth_verdict: max depth 25704, with a real spread across depths

no crashes yet
```
