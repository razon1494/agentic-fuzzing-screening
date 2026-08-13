# Iteration 3

- strategy: `iteration_3.py`
- cost: $0.5594

## Rationale

The generator walks the full TomlParser/TomlLexer grammar (document -> expression -> key_value/table/comment, key/dotted_key, all seven value kinds, array_/inline_table recursion via st.recursive, plus array_table) while instrumenting every production tomlc99's grammar defines. It layers three depth regimes for array_/inline_table (shallow st.recursive trees, mid-depth 10-400 isolated probes, and deep 500-35000 isolated probes) so the histogram spans nominal nesting through the confirmed stack-overflow region without ordinary well-formed documents paying the cost of a slow parse. On top of syntactically-valid generation it deliberately reintroduces measured tomlc99-specific gaps -- raw control bytes and bare CR in basic strings, leading-zero decimals, dotless floats, and malformed \x escapes -- plus low-frequency semantic conflicts (duplicate key/table, array-table redefined as key) and near-valid truncated/mismatched-bracket documents, all riding inside otherwise normal documents via the base_name-uniqueness trick so the malformed edge is always the *only* thing wrong with the document.

## Changes from the previous iteration

- unique_crash_signatures rose from 3 to 4, and it's the same stack-overflow bug family (array/table/mixed nesting) -- per the loop's own guidance to steer away from already-found bugs, trimmed deep_array/deep_table/deep_mixed weights from 4/4/2 (10% total) to 2/2/2 (6% total) rather than expanding them further
- acceptance_rate=39.4% is healthy with headroom to push slightly more malformed input before risking pure-tokenizer-reject territory -- widened normal_document's extra_choice denominator from 30 to 24 and added three new near-valid-malformed cases (unterminated array, unterminated inline table, mismatched array-table close bracket) to broaden the reject-path coverage beyond the four cases already exercised
- productions_never_exercised: none -- no new grammar rules needed reaching, so effort went into deepening the already-confirmed-real superset gap instead: doubled the basic_control_byte weight in string_value (from 1-of-7 to 2-of-8) and let it emit runs of 1-3 control bytes per string instead of always exactly one, plus added bare CR (\x0d) to CONTROL_BYTES since a lone CR outside a CRLF pair is exactly the kind of raw-control-byte leniency the grammar forbids but tomlc99 was measured to accept
- freed the 4% of budget trimmed from deep stress into raising normal_document's overall share from 82% to 86%, since that mode is what exercises the widened malformed-edge cases and the boosted control-byte string content

## Measured results

```
examples=500  accept=144, crash=1, reject=355
acceptance_rate=28.8%
unique_crash_signatures=1
productions_exercised=['array_', 'array_table', 'bool_', 'date_time', 'dotted_key', 'floating_point', 'inline_table', 'integer', 'key_value', 'string', 'table']
depth_histogram=d0:86, d1:109, d2:139, d3:113, d4:23, d10:4, d23:2, d30:1, d64:1, d83:1, d95:1, d151:1, d164:1, d219:2, d244:1, d367:2, d376:1, d400:1, d500:3, d3866:1, d11572:1, d15000:1, d15622:1, d19456:1, d20552:1, d20735:1, d33347:1
acceptance_verdict: 28.8% -- low. Much of the budget is spent on inputs rejected at the front door.
productions_never_exercised: none
depth_verdict: max depth 33347, with a real spread across depths

crash signatures found so far (do not re-target these):
  [28379cb26912] DEADLYSIGNAL x1  minimized='<not reproduced>'
```
