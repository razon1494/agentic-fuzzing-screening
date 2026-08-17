# Agentic Fuzzing without coverage

**Target:** [parson](https://github.com/kgabis/parson) (JSON, C) @ `ba29f4e`. **Grammar:** grammars-v4
`json/JSON.g4` @ `e1c222f`. **Result:** 5 iterations, 2,500 inputs, 0 crashes, $0.86 (91,927 tokens)
of a $5 budget.

## The problem

Fuzzing a parser is easy to do badly. Throw random bytes at a JSON library and nearly every input dies
in the first few characters, so you test the tokenizer thousands of times and the real parser never.
The fix is to generate inputs already shaped like the format, which is what a formal grammar gives
you for free.

This assignment adds a twist: don't write that generator yourself. Give an LLM the grammar, have it
write a [Hypothesis](https://hypothesis.readthedocs.io/) strategy, run the output through a sanitizer
build of the real C library, and feed the measurements back so it can revise. Five rounds, or five
dollars, whichever runs out first. And you may not instrument the target for coverage, which is
normally how you'd know whether a generator improved. So the real question isn't whether an LLM can
write one, because it can, first try. It's what you show it on round two.

## Design

**Grammar and adaptations.** The 77-line JSON grammar goes into the prompt whole, since summarizing
risks quietly dropping a production. But the grammar describes JSON in the abstract, not parson, and
the gap between the two is where the real parsing code lives. Rather than guess, I measured it: 33
boundary inputs plus a bisection against the sanitizer build (`grammar/json-parson/ADAPTATIONS.md`).
parson accepts things the grammar forbids (a trailing comma, anything after the first value, a BOM,
`1.`, raw invalid UTF-8 in strings) and rejects things it allows (duplicate keys, lone surrogates,
exponents that overflow a double). It caps nesting at 2049 for arrays and 2048 for objects, and that
one-level difference is real and repeatable. They go in beside the grammar, because a generator
emitting only grammar-legal text never reaches the superset paths.

**Harness and build.** The hardest thing to get right is what counts as a bug, because "invalid input"
is the parser working correctly. The harness reads stdin, calls `json_parse_string`, and exits 0 when
a value comes back, 1 on a clean `NULL`, 2 if the harness itself fails. Anything else, a fatal signal
or sanitizer abort, is a real bug. The build supplies the abort: ASan and UBSan with
`-fno-sanitize-recover=all`, so undefined behavior stops the process instead of continuing quietly.
One trap silently destroys the experiment: ASan's default exit code is 1,
identical to the reject code, so without `ASAN_OPTIONS=abort_on_error=1` every memory bug gets filed
as a polite rejection. Timeouts get 5 seconds and are triaged as crashes, since a parser that hangs is
a denial-of-service bug, not a pass.

**The loop and its signal.** Each round prompts the model, saves the module, sanity-checks a dozen
examples to catch one that won't even import, runs 500 inputs through the harness, and hands
the summary back. With coverage off the table, three measurements stand in: acceptance rate,
production coverage (each strategy declares which grammar rule it's expanding), and nesting depth. I
chose those three because they map onto the three ways a grammar-derived generator usually fails: it
bounces off the tokenizer, it silently never reaches some rules, or its recursion is cosmetic and
everything comes out flat. All three live in the generator, not the target, so they cost nothing
and break no rules.

## Findings

parson survived all 2,500 inputs under ASan and UBSan with zero crashes. That isn't a broken pipeline:
the crash path was validated first against a toy parser with three planted bugs, all caught,
deduplicated, and minimized correctly (`spine_check/`, 6/6).

| Iteration | Acceptance | Max depth | What drove the change |
|---|---|---|---|
| 0 | 45.0% | 8 | seed from grammar + measured gaps |
| 1 | 40.2% | 7 | dropped an unrecognized production label, widened leaf budget |
| 2 | 58.6% | 2051 | fixed the depth instrumentation bug, added mid-range nesting |
| 3 | 53.2% | 2051 | nested duplicate keys, block comments, more invalid UTF-8 |
| 4 | 52.6% | 2052 | exact wall depths, alternating array/object nesting |

The best moment is iteration 2. The round before shipped a probe aimed at 2,000+ levels of nesting,
and the depth histogram came back topping out at 7. From that single number the model worked out that
its `production()` call was wrapping the whole document instead of each level, rewrote it with an
`ExitStack` entering one context per level, and depth jumped to 2051. That is exactly the "recursive
generator that secretly flattens" failure the assignment warns about, caught by the signal instead of
by luck.

Now the uncomfortable part. The spec notes that a trial run of this exercise, on this same library,
went from zero crashes to finding them reliably within five iterations. Mine didn't, and I think the
signal is why. Depth was the most legible number I gave the model, it moved dramatically once fixed,
and so three of five rounds went into pushing it further. But nesting depth is the one dimension
parson explicitly defends, with a `MAX_NESTING 2048` guard that refuses cleanly instead of blowing the
stack. The loop optimized hard toward a wall the author had already built. Meanwhile acceptance sat
between 40% and 59% every round, my summary called that "healthy" every round, and a signal that keeps
reporting "healthy" creates no pressure to change anything. The proxy worked as designed and steered
somewhere safe.

Still under-tested: the harness only calls `json_parse_string`, so `json_parse_file`, the
`_with_comments` entry point, and the serialization path never ran. Raw invalid UTF-8 is the most
plausible remaining home for a memory bug in a byte-oriented C parser, since parson doesn't validate
encoding, and it reached only about 11% of inputs from iteration 3 on. Mid-range nesting stayed thin,
since the histogram clusters near the bottom and at the wall.

## Challenges

The first live run died on a `JSONDecodeError` that read like a parsing bug and wasn't. `max_tokens`
was too low, adaptive thinking plus a full strategy module blew past it, and the response arrived
truncated mid-string. Raising the cap and checking `stop_reason` before parsing fixed it, at the cost of one
wasted call.

Three judgment calls worth stating outright. Deduplication hashes the top three symbolized frames
after stripping addresses, libc noise, and bare integers, every choice documented in
`fuzzer/triage.py`; it never ran against a real JSON crash, only the toy target, so I can't call it
battle-tested. Timeouts count as crashes and take the same triage path as a sanitizer abort, the
right policy even though nothing came near tripping it. And the harness deliberately
frees the input buffer before the parse tree, so a retained pointer into it would surface as a genuine
use-after-free rather than being masked. Nothing tripped that either, a small positive signal about
parson's lifetime handling.

With more time I'd widen the harness past a single entry point and try differential testing against a
second JSON parser: disagreement is a denser signal than crashing, and catches correctness bugs a
sanitizer never will. With coverage available, the failure above wouldn't have happened at all: it
would have shown iterations 2 through 4 re-walking the same lines at ever-greater depth, and the
pressure to look elsewhere would have arrived on round three instead of in this paragraph.

*Artifacts under `json-parson/`: `grammar/`, `target/`, `strategies/`, `logs/`, `crashes/`.*
