# Agentic Fuzzing: driving an LLM from a grammar to a generator

**Target:** [parson](https://github.com/kgabis/parson) (JSON, C) at pinned commit `ba29f4e`
**Grammar:** grammars-v4 `json/JSON.g4` at pinned commit `e1c222f`
**Result:** 5 iterations, 2,500 inputs, 0 crashes, $0.86 (91,927 tokens) of a $5 budget

## What this is

A fuzzer needs inputs shaped like the format it's testing, or almost everything gets rejected in the
first few bytes. This project gets that shape from a formal grammar, but an LLM writes the generator
instead of a human, then rewrites it five times using measurements from the round before. The hard part
isn't getting an LLM to write a generator. It's deciding what to measure so you can tell whether the
last one was any good, especially with coverage instrumentation banned on the target.

## Design

**Grammar.** The 77-line JSON grammar from grammars-v4 goes into the prompt whole, since summarizing
risks silently dropping a production. But the grammar describes JSON in the abstract, not parson, so
instead of guessing where they disagree I measured it: 33 boundary inputs plus a bisection against the
sanitizer build (`grammar/json-parson/ADAPTATIONS.md`). parson accepts things the grammar forbids (a
trailing comma, garbage after the first value) and rejects things it allows (duplicate keys, lone
surrogate escapes). It caps nesting at 2049 for arrays and 2048 for objects, an exact wall, not a soft one.

**Harness.** The hardest judgment call is what counts as a bug: "invalid input" is correct behavior, a
sanitizer abort or fatal signal is not. The harness calls `json_parse_string` and exits 0 on success, 1
on a clean `NULL`, 2 if the harness itself fails. One trap worth naming: ASan's default exit code is 1,
same as the reject code, so without `ASAN_OPTIONS=abort_on_error=1` every memory bug gets filed as a
polite rejection.

**The loop and its signal.** Each round: prompt the model, save the module, sanity-check a dozen
examples, run 500 through the harness, summarize, feed it back. With coverage off the table, three
things stand in for it: acceptance rate (is the generator clearing the tokenizer), production coverage
(which grammar rules it's actually touched, from each strategy declaring which one it's expanding), and
nesting depth (is the recursion real or cosmetic). All three are things a reviewer would ask about a
generator anyway, and they cost nothing since they live in the generator, not the target.

## Findings

parson survived all 2,500 inputs under ASan and UBSan. No crashes. That's a real result, not a broken
pipeline: the same crash path was checked against a toy parser with three planted bugs, and all three
were caught, deduped, and minimized correctly before any real target existed (`spine_check/`, 6/6).
parson is small and has been fuzzed by plenty of people already; five iterations wasn't enough to find
what's left.

| Iteration | Acceptance | Max depth | Crashes |
|---|---|---|---|
| 0 | 45.0% | 8 | 0 |
| 1 | 40.2% | 7 | 0 |
| 2 | 58.6% | 2051 | 0 |
| 3 | 53.2% | 2051 | 0 |
| 4 | 52.6% | 2052 | 0 |

Acceptance stayed healthy throughout, so inputs reached the parser instead of bouncing off the
tokenizer. The interesting part is depth. Iteration 1 had a probe aimed at 2,000+ levels of nesting, and
the histogram topped out at 7. From that one number the model worked out its `production()` call was
wrapping the whole document instead of each level, fixed it, and depth jumped to 2051 next round. That's
the exact "recursive generator that secretly flattens" failure the assignment calls out, caught by the
signal instead of by luck. Later rounds spent the rest of the budget on documented gaps (duplicate keys,
block comments, malformed UTF-8, both nesting walls), each change tied to a number from the prior summary.

Still under-tested: the harness only calls `json_parse_string`, so `json_parse_file` and the
serialization path never ran, and mid-range nesting got little attention since the histogram clusters
near the bottom and the wall.

## Challenges

The first run died on a `JSONDecodeError` that read like a parsing bug but wasn't: `max_tokens` was too
low, adaptive thinking plus a full strategy blew past it, and the response got cut off mid-string.
Raising the cap and checking `stop_reason` before parsing fixed it.

Deduplication hashes the top three stack frames after stripping addresses and libc noise, with every
normalization choice documented in `fuzzer/triage.py`. It never ran against a real crash here though,
only the toy target, so I can't call it battle-tested.

One deliberate call: the harness frees the input buffer before the parse tree, so a retained pointer
into it would show up as a genuine use-after-free instead of getting masked. Nothing tripped it, a small
positive sign for parson's lifetime handling.

With more time or coverage available, I'd try differential testing against a second JSON parser first
(disagreement is a denser signal than crashing and catches correctness bugs a sanitizer never will),
then spend more budget at the byte level, since parson doesn't validate UTF-8 and that's the most
plausible place left for a memory bug in a byte-oriented C parser.

---

*Artifacts: `grammar/json-parson/`, `target/json-parson/`, `strategies/json-parson/`,
`logs/json-parson/`, `crashes/json-parson/NONE_FOUND.md`.*
