# Iteration 4

- strategy: `iteration_4.py`
- cost: $0.3543

## Rationale

The measured 28.8% acceptance rate was traced to two deliberate-malformation knobs stacked on top of otherwise well-formed documents: normal_document's extra_choice fired a guaranteed-reject probe (unterminated tokens, dangling commas, mismatched brackets, duplicate key/table) on 9 of 24 branches (~37.5%) applied to 86% of all documents, and string_value's basic_invalid_escape fired on 1 of 8 (12.5%) of every string terminal, which appears repeatedly per document via values and quoted keys. Together these accounted for most of the measured reject mass. Both were reduced (extra-probe injection to ~9%, invalid-escape weight to ~8.3%) while keeping every distinct edge case alive so the rejection paths stay exercised, just far less often. The confirmed-accepted superset gaps (leading zero, dotless float, control bytes in basic strings) are untouched since they cost no acceptance. Deep/mid nesting stress (the primary lever per ADAPTATIONS.md, since tomlc99's recursion has no depth cap) is unchanged in weight since it never causes rejects -- only accept or crash -- and the existing depth histogram already shows a genuine spread from 0 to 33347. All required grammar-rule names are still wrapped in production()/record_production() so coverage stays fully populated.

## Changes from the previous iteration

- Removed '\\/' from BASIC_ESCAPES: not a real TOML escape, was an unforced reject-risk source of unknown magnitude in every basic string that rolled it (grammar-vs-target correctness fix, not motivated by a specific number but by process of elimination once the two dominant reject sources below were identified).
- Reduced string_value's 'basic_invalid_escape' weight from 1/8 (12.5%) to 1/12 (~8.3%) of string instances -- this kind is a guaranteed per-instance reject and strings recur often across values and quoted keys, so it was a material contributor to the measured 28.8% acceptance_rate.
- Reduced normal_document's forced-malformed extra injection from 9/24 (~37.5%) to a flat ~9% (1-in-11) probability, motivated directly by acceptance_rate=28.8% and the verdict 'low ... much of the budget is spent on inputs rejected at the front door' -- 6 of the 9 original branches are guaranteed rejects applied to 86% of documents, which alone explains most of the shortfall from a healthy acceptance level.
- Refactored the extra-probe selection into a named _EXTRA_KINDS catalogue chosen uniformly at the new lower injection rate, so all 9 distinct edge probes (duplicate key, duplicate table, array-table-redefined-as-key, empty-comma array, trailing-comma inline table, unterminated string/array/table, mismatched array-table close) remain reachable and none are dropped, only made less frequent.
- Left deep/mid stress-document weighting (14% combined), the crash-adjacent stack-overflow probes, and all production()/record_production() coverage instrumentation unchanged, since depth_histogram already showed a genuine spread (d0 through d33347) and productions_never_exercised was already 'none' -- the single lever this round was acceptance_rate, not depth or coverage breadth.

## Measured results

```
examples=500  accept=240, reject=260
acceptance_rate=48.0%
unique_crash_signatures=0
productions_exercised=['array_', 'array_table', 'bool_', 'date_time', 'dotted_key', 'floating_point', 'inline_table', 'integer', 'key_value', 'string', 'table']
depth_histogram=d0:97, d1:111, d2:120, d3:102, d4:37, d10:2, d60:1, d61:1, d83:1, d195:1, d235:1, d240:1, d272:1, d344:1, d383:1, d500:3, d612:7, d795:7, d1280:1, d3935:1, d17661:1, d18843:1, d21594:1
acceptance_verdict: 48.0% -- healthy: a real mix of accepted and rejected inputs.
productions_never_exercised: none
depth_verdict: max depth 21594, with a real spread across depths

no crashes yet
```
