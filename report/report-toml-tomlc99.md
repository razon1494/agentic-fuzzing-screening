# Bonus target: tomlc99 (TOML)

**Supplementary to [`report.md`](report.md), the primary submission (JSON/parson).** Same pipeline,
same `fuzzer/` spine, zero code changes to support this target — see the main
[`README.md`](../README.md#targets) for why a second target was added. This report is deliberately
shorter: the design rationale (crash-vs-rejection contract, the proxy signal, survey/shrink passes,
dedup mechanics) is identical to the primary report and isn't repeated here.

**Target:** [tomlc99](https://github.com/cktan/tomlc99) at pinned commit `29076df`
**Grammar:** grammars-v4 `toml/{TomlParser,TomlLexer}.g4` at pinned commit `e1c222f`
**Result:** 5 iterations, 2,500 inputs, **4 crash signatures, 1 confirmed root cause**, $2.76 of a $5 budget

## Findings

### A real bug, found twice — once by hand, once by the loop

Step 1 probing (before any agentic loop ran) found that `toml.c` has **no nesting-depth cap** — unlike
parson's explicit `MAX_NESTING 2048` — and confirmed a stack overflow at depth 50,000, with the exact
boundary sitting somewhere in the 23,000–27,000 range depending on shape and process-to-process jitter
(`grammar/toml-tomlc99/ADAPTATIONS.md`). The agentic loop, seeded with that finding, independently
generated inputs that reached the same class of crash through its own deep-nesting strategies —
confirming the hand-probe wasn't a one-off and that the loop's depth signal genuinely steers toward it.

### Four signatures, one bug

The triage pipeline reported four unique crash signatures. Reading the actual stack traces, all four
are `AddressSanitizer: stack-overflow`, and the *frame identity* differs only because of what happened
to be executing when the guard page was hit — a `malloc` inside `expand`/`expand_arritem` (array
growth), a `strnlen` inside `STRNDUP`/`normalize_key` (key duplication), or nothing captured at all
(`<empty stack>` — the unwinder itself ran out of stack). Underneath all four, the actual call chain is
thousands of frames of the same two functions recursing without a depth check:

```
parse_array -> parse_array -> parse_array -> ... (array nesting)
parse_inline_table -> parse_keyval -> parse_inline_table -> ... (inline-table nesting)
```

This is exactly the dedup failure mode flagged as untested in the primary report's Challenges section
— "none of this ran on a real crash — it is validated only against the toy target." Now it has, and
top-N-frame hashing genuinely over-counts for a stack-overflow class of bug: the crash site is
determined by scheduler/allocator timing, not by the root cause, so four samples of the same overflow
can legitimately hash to four different signatures. Iteration 3's own refinement reasoning caught this
independently — *"unique_crash_signatures rose from 3 to 4, and it's the same stack-overflow bug
family"* — and correctly stopped investing further budget in re-finding it, redirecting toward
acceptance rate instead. The **honest count is one confirmed root cause** (unbounded parser recursion),
reachable via at least two distinct code paths (array nesting, inline-table/key nesting), reported as
four raw signatures. All four reproducers were re-verified standalone against the pinned build and
crash deterministically.

### Reproducers are large, and that's diagnostic, not a bug in the pipeline

Three of the four reproducers are marked `minimized: NO — crash too rare to re-reach` (53–137 KB
each). This is a direct consequence of the boundary instability documented in `ADAPTATIONS.md`: because
the exact crashing depth shifts by roughly ±1,000 between process invocations, Hypothesis's shrinker
tries a smaller candidate, it doesn't crash on that particular run, and the shrinker correctly declines
to report a reproducer it couldn't re-trigger — keeping the original large input instead of a false
minimization. This is the shrinker behaving correctly under a genuinely flaky target, not a defect in
`campaign.minimize`.

### Evolution

| Iteration | Acceptance | Max depth | Productions | Crashes |
|---|---|---|---|---|
| 0 | 6.2% | 25,704 | 11 | 0 |
| 1 | 43.0% | 33,701 | 11 | 3 |
| 2 | 39.4% | 31,381 | 11 | 4 |
| 3 | 28.8% | 33,347 | 11 | 1 (re-hit) |
| 4 | 48.0% | 21,594 | 11 | 0 (re-hit) |

Iteration 0's 6.2% acceptance is the clean version of the failure mode the loop is built to catch: a
generator that puts an uncapped-depth nested draw inside *every* ordinary document, so ~40% of
otherwise-valid documents got dragged down by one runaway field. Iteration 1 diagnosed this from the
number alone and isolated deep nesting into its own single-line strategy — acceptance jumped to 43%
in one round. From there the loop did exactly what it's supposed to: iteration 2 found the crash family
and immediately reduced deep-stress weight rather than escalating it further; iterations 3–4 spent the
remaining budget on acceptance rate and byte-level string content, per the target-specific guidance in
`ADAPTATIONS.md` that tomlc99's numeric handling is comprehensive and not worth the budget JSON's
generator spent there.

## Challenges specific to this target

- **A genuinely flaky crash boundary makes "found the bug" a probabilistic statement**, not a
  deterministic one, in a way the JSON target never was. parson's wall was exact to the input every
  time; tomlc99's crash depends on process-to-process stack layout. The pipeline handles this
  correctly (verify-before-report, minimizer declines to over-claim), but it means "at depth X" is not
  a fact about the bug — it's a fact about one run.
- **Dedup over-splitting is now a demonstrated failure mode, not a hypothetical one.** The fix isn't
  implemented here — re-normalizing after the fact based on knowing the answer would be circular — but
  the honest fix for a future iteration would be a secondary grouping pass keyed on "sanitizer error
  class + whether the top frames are dominated by a single repeated function," which would collapse
  all four of these into one reported bug automatically.
- **Cost was higher than JSON's** ($2.76 vs $0.86) — largely iteration 2's single $0.72 call, driven by
  a 157K-token input once the previous iteration's strategy code plus large first-seen crash inputs
  were included in the feedback prompt. A future version should truncate or summarize oversized
  `first_input` values before they go back into context, rather than passing them through whole.
