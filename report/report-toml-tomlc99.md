# Bonus target: tomlc99 (TOML)

**Supplementary to [`report.md`](report.md), which is the primary submission.** Same pipeline, same
`fuzzer/` spine, no code changes to support this target. The design rationale (crash-vs-rejection
contract, the proxy signal, survey and shrink passes, dedup mechanics) is identical to the primary
report and isn't repeated here.

**Target:** [tomlc99](https://github.com/cktan/tomlc99) @ `29076df`. **Grammar:** grammars-v4
`toml/{TomlParser,TomlLexer}.g4` @ `e1c222f`. **Result:** 5 iterations, 2,500 inputs, **4 crash
signatures, 1 confirmed root cause**, $2.76 of a $5 budget.

## Why a second target

The JSON run found nothing, and a single negative result is hard to read. It could mean parson is
solid, or it could mean my pipeline can't find bugs at all. Adding a second library answers two
questions at once: is the spine actually target-independent, and does a less-hardened parser behave
differently? Both answers came back yes. Nothing in `outcomes.py`, `runner.py`, `triage.py`,
`coverage.py`, or `campaign.py` changed, and TOML produced a real bug.

## Findings

### A real bug, found twice

Step 1 probing, before any agentic loop ran, turned up the important structural fact: `toml.c` has no
nesting-depth cap at all. parson has an explicit `MAX_NESTING 2048` and refuses cleanly past it;
tomlc99 just keeps recursing. A hand-built input at depth 50,000 overflows the stack, and the actual
boundary sits somewhere between roughly 23,000 and 27,000 depending on the shape and on
process-to-process jitter (`grammar/toml-tomlc99/ADAPTATIONS.md`).

The loop was seeded with that finding, and then independently generated inputs that reached the same
crash through its own deep-nesting strategies. That matters more than finding it by hand did, because
it shows the depth signal genuinely steers toward the bug rather than just describing it after the
fact.

### Four signatures, one bug

The triage pipeline reported four unique crash signatures. Reading the actual stack traces, all four
are `AddressSanitizer: stack-overflow`, and the frame identity differs only because of what happened
to be executing when the guard page got hit: a `malloc` inside `expand`/`expand_arritem` during array
growth, a `strnlen` inside `STRNDUP`/`normalize_key` during key duplication, or nothing captured at
all (`<empty stack>`, where the unwinder itself ran out of stack). Underneath all four, the real call
chain is thousands of frames of the same two functions recursing without a depth check:

```
parse_array -> parse_array -> parse_array -> ...                (array nesting)
parse_inline_table -> parse_keyval -> parse_inline_table -> ...  (inline-table nesting)
```

This is exactly the dedup failure mode the primary report flags as untested, and now it has been
tested. Top-N-frame hashing over-counts for a stack-overflow class of bug, because the crash site is
decided by allocator and scheduler timing rather than by the root cause, so four samples of one
overflow can legitimately hash to four different signatures. Iteration 3 caught this on its own,
noting in its refinement reasoning that *"unique_crash_signatures rose from 3 to 4, and it's the same
stack-overflow bug family"*, then correctly stopped spending budget re-finding it and redirected
toward acceptance rate. The honest count is **one confirmed root cause**, unbounded parser recursion,
reachable by at least two distinct code paths, reported as four raw signatures. All four reproducers
were re-verified standalone against the pinned build and crash deterministically.

### Large reproducers are diagnostic, not a pipeline defect

Three of the four reproducers carry `minimized: NO, crash too rare to re-reach` and run 53 to 137 KB
each. That follows directly from the boundary instability above. Because the exact crashing depth
shifts by roughly a thousand levels between invocations, the shrinker tries a smaller candidate, that
candidate happens not to crash on that particular run, and the shrinker declines to report a
reproducer it couldn't re-trigger. It keeps the original large input instead of publishing a false
minimization. That's the shrinker behaving correctly against a genuinely flaky target, not a bug in
`campaign.minimize`.

### How the generator evolved

| Iteration | Acceptance | Max depth | Crashes | What drove the change |
|---|---|---|---|---|
| 0 | 6.2% | 25,704 | 0 | seed from grammar + measured gaps |
| 1 | 43.0% | 33,701 | 3 | isolated deep nesting out of ordinary documents |
| 2 | 39.4% | 31,381 | 4 | found the crash family, reduced deep-stress weight |
| 3 | 28.8% | 33,347 | 1 (re-hit) | recognized one bug family, redirected to acceptance |
| 4 | 48.0% | 21,594 | 0 (re-hit) | byte-level string content, acceptance recovery |

Iteration 0's 6.2% acceptance is the textbook version of the failure the loop exists to catch. The
generator put an uncapped-depth nested draw inside *every* ordinary document, so roughly 40% of
otherwise-valid documents got dragged down by one runaway field. This is the "correcting a generator
that was mostly being rejected" case the assignment calls out, and it happened here rather than on the
JSON target. Iteration 1 diagnosed it from the acceptance number alone, moved deep nesting into its
own dedicated strategy instead of contaminating every document, and acceptance jumped to 43% in a
single round.

From there the loop behaved the way I'd hoped. Iteration 2 found the crash family and immediately
reduced deep-stress weight rather than escalating it, which is the right instinct once a bug is
already reproducible. Iterations 3 and 4 spent the remaining budget on acceptance rate and byte-level
string content, following the target-specific note in `ADAPTATIONS.md` that tomlc99's numeric handling
is thorough and not worth the budget the JSON generator spent there.

## Challenges specific to this target

**A flaky crash boundary makes "found the bug" a probabilistic claim.** parson's nesting wall was exact
to the input every single time. tomlc99's crash depends on process stack layout, so "at depth X" is a
fact about one run, not about the bug. The pipeline handles this correctly, verifying before reporting
and declining to over-minimize, but it changes what the evidence means.

**Dedup over-splitting is now demonstrated rather than hypothetical.** I deliberately did not
implement a fix, because re-normalizing after already knowing the answer would be circular. The honest
fix for a future iteration is a secondary grouping pass keyed on the sanitizer error class plus
whether the top frames are dominated by a single repeated function, which would collapse all four of
these into one reported bug automatically.

**Cost ran higher than JSON's**, $2.76 against $0.86, almost entirely from iteration 2's single $0.72
call. That call carried a 157K-token input, because the previous iteration's full strategy code plus
several large first-seen crash inputs all went back into the feedback prompt verbatim. A future
version should truncate or summarize oversized `first_input` values before they re-enter context.

*Artifacts under `toml-tomlc99/`: `grammar/`, `target/`, `strategies/`, `logs/`, `crashes/`.*
