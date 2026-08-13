# Agentic Fuzzing: driving an LLM from a grammar to a generator

**Target:** [parson](https://github.com/kgabis/parson) (JSON, C) at pinned commit `ba29f4e`
**Grammar:** grammars-v4 `json/JSON.g4` at pinned commit `e1c222f`
**Result:** 5 iterations, 2,500 generated inputs, 0 crashes, $0.86 of a $5 budget

## The problem

Fuzzing a parser by throwing random bytes at it wastes almost every input on
garbage the tokenizer rejects in its first few characters. The interesting bugs
live deeper — in recursion, in number conversion, in escape handling — and
reaching them requires inputs that are *structurally plausible*. This project
gets that structure from a formal grammar, but not by writing a generator by
hand: an LLM reads the grammar and writes the generator, then rewrites it across
five rounds using measurements from the previous round. The engineering question
is not "can an LLM write a Hypothesis strategy" — it can — but **what do you
measure to tell it whether the last one was any good**, given that the exercise
forbids instrumenting the target for coverage.

## Design

### Grammar, and where the grammar is wrong

The ANTLR JSON grammar is 77 lines and goes into the prompt whole; summarizing it
would silently drop productions. But the grammar describes *JSON*, and the target
is *parson*, and those are not the same language. Rather than infer the
difference from parser source, I measured it: 33 boundary inputs plus a bisection
run against the sanitizer build, yielding twelve documented differences
(`grammar/ADAPTATIONS.md`).

parson is a **superset** in places the grammar forbids — it accepts a single
trailing comma (`{"a":1,}`), ignores anything after the first value (`{} trailing`,
which is also why `// hi` appears to work while a real `/* */` comment does not),
accepts `1.`, a UTF-8 BOM, and raw invalid UTF-8 inside strings. It is a
**subset** elsewhere — it rejects duplicate keys, lone surrogate escapes, and
exponents that overflow a double. Recursion is capped, and the cap is not where
the documentation implies: bisection put the deepest accepted array nesting at
**2049** and objects at **2048**, a repeatable one-level difference arising from
where the nesting counter increments on the two production paths.

These gaps ship in the prompt alongside the grammar, and they change what the
generator is worth. Without them the model spends its budget on duplicate keys —
listed in the assignment's own edge-case list, and a guaranteed rejection here —
while never reaching the code past the grammar that parson does accept.

### Harness: crash vs. rejection

The single most consequential judgment call is what counts as a bug. A parser
answering "this is not valid JSON" is working correctly; a parser reading past a
buffer is not. The C harness reads stdin, calls `json_parse_string`, and exits
**0** on a successful parse, **1** on a `NULL` return (a well-formed rejection),
and **2** if the harness itself fails — so a broken harness can never masquerade
as a clean parse. Everything else — a fatal signal, or a sanitizer report on
stderr — is a bug.

That contract has a trap in it. AddressSanitizer's *default* exit code is 1,
which is exactly the rejection code, so a straightforward build files every
memory-safety bug as "the parser politely said no." The runner therefore forces
`ASAN_OPTIONS=abort_on_error=1`, turning sanitizer findings into SIGABRT, and the
build uses `-fno-sanitize-recover=all` so a pure UB report aborts instead of
printing and exiting 0. Sanitizer output in stderr overrides the exit code
entirely: a UB report that somehow exited 0 is still a bug.

Two further policies, both documented rather than assumed. **Leak detection is
off** — an allocating parser leaks on nearly every input, and that noise would
drown the memory-safety signal this exercise targets. **Timeouts count as
crashes**, per the spec: a parser that hangs is a denial-of-service bug, and it
goes through the same triage pipeline as an abort.

The harness was validated before any fuzzing ran: 19 hand-picked samples, all
classified correctly, and both sanitizer runtimes confirmed linked into the
binary. A sanitizer build whose flags were silently dropped reports clean runs
forever, so this is checked rather than trusted.

### The loop, and the signal that steers it

Each iteration: prompt the model → write the module to disk → import and
spot-check it → run 500 examples through the harness → summarize → feed back.

The assignment bans coverage instrumentation of the *target*. It says nothing
about instrumenting the *generator*. Every strategy the model writes declares
which grammar production it is expanding (`with production("arr"):`), which
yields two signals for free, entirely blackbox:

1. **Production coverage** — which grammar rules the generator has actually
   emitted. A production that never fires is grammar that is provably untested,
   and naming it is the most direct lever available.
2. **Nesting depth** — a histogram of how deep recursion actually went. A
   generator can look recursive and emit only flat documents; this catches it.

Paired with the parser's own **acceptance rate**, that is the complete steering
signal. Acceptance rate is the guardrail: near zero means the generator is being
turned away at the front door and nothing past the tokenizer is under test; near
one means it only emits well-formed documents and never probes error handling.
The summary reports each as a *verdict* rather than a bare number, because the
model acts on judgments more reliably than on statistics.

Two smaller decisions matter. Hypothesis is used in **two separate passes** — a
survey pass running `Phase.generate` only, so the run never stops early and every
crash in 500 examples is observed, then a targeted shrink pass per unique
signature so the reported reproducer is genuinely minimal rather than the first
one seen. And a module that fails to import is **not** a dead iteration: its
traceback goes back as the feedback, and the next round repairs it.

## Findings

### No crashes

parson at `ba29f4e` survived 2,500 grammar-derived inputs under ASan and UBSan
without a single crash, hang, or sanitizer report. This is a real result, not a
pipeline failure — the pipeline's crash path was validated end-to-end against a
deliberately buggy toy parser exercising a stack-buffer-overflow, a signed-integer
overflow, and an infinite loop, all three detected, deduplicated, and minimized
correctly (`spine_check/`, 6/6). parson is a small, mature, widely deployed
library whose obvious inputs have been fuzzed by others for years; the honest
conclusion is that this budget was not enough to reach what remains.

### How the generator evolved

| Iteration | Acceptance | Max depth | Productions | Crashes |
|---|---|---|---|---|
| 0 | 45.0% | 8 | 10 | 0 |
| 1 | 40.2% | 7 | 9 | 0 |
| 2 | 58.6% | **2051** | 9 | 0 |
| 3 | 53.2% | 2051 | 9 | 0 |
| 4 | 52.6% | 2052 | 9 | 0 |

Acceptance stayed in a healthy 40–59% band throughout, so inputs were reaching
the parser proper rather than bouncing off the tokenizer, and all nine grammar
productions were covered from iteration 1 onward. The interesting movement is in
the depth column, and it is the clearest evidence the signal did real work:

- **Iteration 0 → 1.** The summary flagged a production recorded under the name
  `json`, outside the grammar's rule set. The model dropped the synthetic label.
- **Iteration 1 → 2 — the loop catching a bug I would have missed.** Iteration 1
  contained a deep-nesting probe explicitly targeting depth 2000+, and the depth
  histogram topped out at **7**. From that number alone the model diagnosed the
  cause: the probe built its string in a plain loop and entered the `production()`
  context once for the *whole document*, so a 2,000-level document was recorded
  as depth 1. It rewrote the probe with `contextlib.ExitStack`, entering one
  context per nesting level. Max depth moved from 7 to 2051. This is precisely
  the "recursive generator that flattens in practice" failure the assignment
  warns about, and the proxy signal caught it without any coverage data.
- **Iterations 3–4.** With structure healthy, the remaining budget went to the
  documented gaps: nested duplicate keys, double trailing commas, genuine block
  comments, four distinct classes of malformed UTF-8, and probes bracketing both
  nesting walls — including a mixed `[`/`{` alternating probe that exercises both
  counter paths in a single document, motivated directly by the one-level
  array/object discrepancy recorded during Step 1.

Iteration 4's reasoning is representative of the whole loop: *"depth histogram
had zero examples at d2046, d2049, d2052 despite the walls sitting at array
2049/2050 and object 2048/2049 — replaced the broad ranges with sampled_from over
the exact bracketing depths."* Every change cites the number that motivated it.

### Still under-tested

The harness calls exactly one entry point. `json_parse_string_with_comments`,
`json_parse_file`, and the entire serialization path are untouched, and a
round-trip (parse → serialize → re-parse) would exercise far more of the library.
The depth histogram is dense at 1–6 and at the 2044–2052 wall but sparse between
— roughly one example each at depths 7 through 720 — so the middle of the
recursion range is thin. Numeric conversion near double-precision boundaries got
only incidental attention. And the harness caps input at 1 MiB, so pathological
large-input behavior is out of scope by construction.

## Challenges

**The token budget nearly ate an iteration.** The first run died parsing the
model's response with "unterminated string." The cause was not the parser: the
response had hit `max_tokens`, because adaptive thinking and a 400-line module
share that budget, and the JSON was truncated mid-value. The fix was to raise the
cap and — more importantly — check `stop_reason` *before* parsing, so an
exhausted budget reports itself instead of masquerading as malformed JSON. Cost
of the lesson: about $0.25 and one failed run.

**Deduplication is designed but unexercised.** Crash signatures hash the top
three symbolized frames with sanitizer-runtime and libc frames stripped and
addresses, line numbers, and bare integers normalized away — every choice
documented with its failure mode in `fuzzer/triage.py`. Stripping *all* bare
integers is the aggressive one: UBSan writes "index 16 out of bounds for type
'char [16]'", and keeping that index would split one bug across many signatures.
Merging is the safer error, since a wrongly-merged pair is caught on manual
inspection while a split bug silently inflates the headline count. Against parson
none of this ran on a real crash — it is validated only against the toy target,
and I would not claim it battle-tested.

**A subtlety in the harness worth flagging.** The input buffer is freed *before*
the parse tree, deliberately: parson's API returns an owning tree, so nothing it
returns may point into our buffer, and a retained pointer would surface as a
genuine use-after-free. Nothing tripped it, which is a small positive result
about parson's lifetime handling.

**Prompt caching worked, and the ledger shows it.** The grammar and adaptations
sit in a cached system prefix ahead of the per-iteration feedback; all five
iterations read 3,950 tokens from cache rather than paying full input price.
Total spend was **$0.8584** across **91,927 tokens** — well inside the $5 cap,
with the iteration cap binding first.

**What I would do differently.** With coverage available, production coverage
would become a fallback rather than the primary signal, and the loop could target
uncovered branches in `parson.c` directly instead of inferring reach from the
grammar side. Without coverage, the highest-value next steps are differential
testing against a second JSON parser — disagreement is a much denser bug signal
than crashing, and finds correctness bugs a sanitizer never will — and extending
the harness to the serialization round-trip. I would also spend a larger share of
the budget below the grammar, at the byte level: parson does not validate UTF-8,
which makes the encoding boundary the most plausible remaining home for a
memory-safety bug in a byte-oriented C parser.

---

*Artifacts: `grammar/` (source + measured adaptations), `target/` (build, harness,
19-sample validation), `strategies/iteration_0..4.py` and `final.py`,
`logs/iteration_N.md` (per-round rationale, changes, and measurements),
`crashes/NONE_FOUND.md`.*
