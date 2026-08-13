# Grammar vs. reality: where tomlc99 and `TomlParser.g4`/`TomlLexer.g4` disagree

Same method as `grammar/json-parson/ADAPTATIONS.md`: every row below was measured
against the sanitizer build at the pinned commit
(`targets/probe_toml.py`, `targets/probe_toml_depth.py`,
`targets/probe_toml_bisect.py` — gitignored scratch, reproducible from this doc),
not inferred from reading `toml.c`.

**This target crashed during Step 1 probing, before the agentic loop ran.**
That is unusual — the JSON/parson target needed the full loop and found nothing
— and it changes the shape of this document: the headline finding here is a
real stack-overflow bug, not just an accept/reject boundary.

## The bug: unbounded recursion → stack overflow

`toml.c` has no nesting-depth cap (`grammar/toml-tomlc99/SOURCE.md` already
flagged this from reading the source; here it is confirmed by triggering it).
Both nested arrays (`[[[...]]]`) and nested inline tables (`{a={a={...}}}`)
recurse through the parser with no depth check, and deep enough nesting blows
the C stack:

```
$ printf 'a = %s1%s\n' "$(printf '['%.0s {1..50000})" "$(printf ']'%.0s {1..50000})" \
    | target/toml-tomlc99/build/tomlc99_harness
==429==ERROR: AddressSanitizer: stack-overflow on address 0x7fffa67f3ff8
SUMMARY: AddressSanitizer: stack-overflow
```

**The boundary is not a clean wall — this is itself worth recording.** Bisecting
between a known-safe depth (20,000) and a known-crashing one (50,000):

| Shape | Bisected boundary | Repeated at that depth (5 runs) |
|---|---|---|
| `[[[...]]]` (array) | ~23,793–23,794 | **flaky**: `accept, crash, accept, crash, crash` |
| `{a={a={...}}}` (inline table) | 26,166 / 26,167 | stable: 5/5 accept at 26,166, 5/5 crash at 26,167 |

The array boundary genuinely varies run-to-run at the same input and depth —
confirmed by five repeated runs each at depths 23,000 / 23,500 / 23,793 / 23,794
/ 24,000, where only the extremes (23,000 and below: always safe; 24,000 and
above: always crash) were deterministic. This is consistent with a pure
stack-overflow mechanism rather than an explicit counter: `ulimit -s` reports an
8 MiB stack, and exactly how much of it is already consumed by argv/envp/ASan's
own frames varies slightly per process invocation, shifting exactly how many
recursive calls fit before the guard page is hit. **Contrast with parson's
JSON nesting wall, which was exact and reproducible to the input** (`2048`/`2049`
every time) — that was an explicit counter with a fixed limit; this is a raw
resource exhaustion with no limit at all, and the difference in determinism is
the signature of that difference in root cause.

This is exactly the class of bug the assignment is built to find: real,
memory-safety-adjacent, and invisible to a generator that never nests deeply —
which is why depth was one of the two coverage-independent signals the loop
tracks (`fuzzer/coverage.py`, unchanged from the JSON target).

## Superset — tomlc99 accepts what the grammar/TOML spec forbids

| Input | Spec / grammar | tomlc99 | Note |
|---|---|---|---|
| `a = 01` | reject (leading zeros forbidden except bare `0`) | **accept** | Same class of gap as parson's `1.` — a numeric-literal edge the lexer doesn't enforce |
| `a = .5` | reject (a float needs at least one digit on both sides of the decimal point) | **accept** | Same family: a digit the lexer should require but doesn't |
| `a = "` + control byte 0x01 + `"` | reject (raw control chars forbidden in basic strings, tab excepted) | **accept** | Byte-level leniency, same family as parson's raw-invalid-UTF-8-in-string gap |
| `[[a]]\nb=1\na=2` | reject (`a` is already an array-of-tables; redefining it as a key is a semantic conflict the TOML spec calls out explicitly) | **accept** | Cross-statement semantic check the grammar (purely syntactic) has no way to express and tomlc99 doesn't enforce either |

## Subset — tomlc99 rejects what the grammar allows

The ANTLR grammar is purely syntactic — `key_value` and `table` have no
uniqueness constraint — so any semantic rejection is a subset gap by
construction, the same framing used for parson's duplicate-key rejection.

| Input | Grammar | tomlc99 | Note |
|---|---|---|---|
| `a = 1\na = 2` | accept | **reject** | Duplicate top-level key |
| `[a]\nb=1\n[a]\nc=2` | accept | **reject** | Duplicate table header |

## Agreement — both accept or both reject as expected

Confirmed so the generator doesn't waste refinement rounds "fixing" already-correct
behavior: all seven value types parse (basic/literal/multiline strings, inline
tables, arrays, both table-header forms, dotted keys); numeric literal forms
(hex/octal/binary/underscore-separated/exponent/`inf`/`nan`) all accept; all four
date-time forms accept; comments, CRLF line endings, tab indentation, and a
missing trailing newline are all tolerated; a correctly-formed `\uXXXX` escape
accepts and a malformed `\x` escape rejects; an empty document and a
whitespace-only document both accept (an empty TOML document is valid TOML).
Note for anyone porting JSON intuition: `a = +1` is **valid** TOML (the spec
explicitly permits a leading `+` on numbers) — this is agreement, not a gap;
it was only worth checking because JSON's grammar forbids it.

## What this means for the generator

1. **Depth is the primary lever, more than for JSON.** parson's wall is a
   contained, deterministic limit at ~2048; tomlc99 has no limit at all, and
   the crash is confirmed to exist at depth 50,000 with the boundary itself
   sitting somewhere in the 23,000–27,000 range depending on shape and process
   jitter. The generator should be able to reach *far* deeper than the JSON
   target ever needed to, for both arrays and inline tables.
2. **Byte-level string content is worth the same attention as JSON's.** Raw
   control bytes inside basic strings are accepted rather than validated,
   mirroring parson's under-validated string content.
3. **Don't spend budget on numeric edge cases the way JSON's generator did.**
   tomlc99's numeric handling (hex/octal/binary/underscore/exponent/inf/nan) is
   comprehensive and grammar-conformant; the payoff there is lower than for
   depth or byte-level string content.
4. **Cross-statement semantics (duplicate keys/tables) are guaranteed
   rejections**, same as parson's duplicate-key case — worth a low-frequency
   presence to exercise the rejection path, not a primary strategy.
