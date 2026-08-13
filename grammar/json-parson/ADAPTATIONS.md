# Grammar vs. reality: where parson and `JSON.g4` disagree

The assignment asks for the gap between the formal grammar and what the library
actually accepts. Everything below was **measured**, not inferred from reading
parson's source: each row is a real input run through the sanitizer build at the
pinned commit (`targets/probe_gaps.py`, `targets/probe_nesting.py` — both in the
gitignored `targets/` scratch area, reproducible from this doc).

Method: 33 boundary inputs, plus a bisection to find the exact nesting wall.
**No input in this set crashed** — every disagreement below is an accept/reject
difference, not a bug. That is the expected starting point, and it is why the
generator needs refinement rather than luck.

## Superset — parson accepts what the grammar forbids

These are the interesting ones. Each is a code path that exists *past* the strict
grammar, so a generator that only emits grammar-legal text will never reach it.

| Input | `JSON.g4` | parson | Note |
|---|---|---|---|
| `{"a":1,}` | reject | **accept** | single trailing comma in an object |
| `[1,2,]` | reject | **accept** | single trailing comma in an array |
| `{} trailing` | reject | **accept** | `json_parse_string` is documented as parsing the *first* value; anything after it is ignored, whereas the grammar's `json : value EOF` demands the input end |
| `{"a":1} // hi` | reject | **accept** | *not* comment support — a consequence of the trailing-garbage tolerance above. The genuine comment form `{"a":1 /* hi */}` is rejected, as it should be by the non-`_with_comments` entry point |
| `1.` | reject | **accept** | grammar's `('.' [0-9]+)?` requires at least one digit after the dot |
| `\xEF\xBB\xBF{}` | reject | **accept** | UTF-8 BOM; the grammar has no BOM production |
| `"\xFF\xFE"` | reject | **accept** | raw invalid UTF-8 inside a string. `SAFECODEPOINT` is defined over codepoints; parson works on bytes and does not validate encoding |
| `{"a":1}\x00garbage` | n/a | **accept** | API boundary, not grammar: the entry point takes a C string, so an embedded NUL truncates the input. Everything past the first NUL is invisible to the library |

## Subset — the grammar allows what parson rejects

Budget-relevant: a generator that emits these often is spending examples on
guaranteed rejections.

| Input | `JSON.g4` | parson | Note |
|---|---|---|---|
| `{"a":1,"a":2}` | accept | **reject** | duplicate keys. The grammar's `obj : '{' pair (',' pair)* '}'` places no uniqueness constraint; parson's object insert fails on a repeat and the whole parse fails. Also holds nested (`{"x":{"a":1,"a":2}}`) |
| `"\ud800"` | accept | **reject** | `fragment UNICODE : 'u' HEX HEX HEX HEX` matches any four hex digits, including unpaired surrogates; parson rejects them |
| `1e999` | accept | **reject** | grammar puts no bound on the exponent; parson rejects values that overflow a `double` |
| `[` × 2050 | accept | **reject** | grammar recursion is unbounded; parson caps nesting (`MAX_NESTING 2048`) |

### Measured nesting wall

| Shape | Deepest accepted | First rejected |
|---|---|---|
| Arrays `[[[…]]]` | **2049** | 2050 |
| Objects `{"a":{"a":…}}` | **2048** | 2049 |

The one-level difference between the two shapes is real and repeatable — the
nesting counter is incremented at a slightly different point on the two
production paths. Worth knowing because a generator aiming "just under the wall"
has a different target depth depending on which container it is nesting.

Rejection at the wall is clean (exit 1, no sanitizer output): parson refuses
rather than blowing the C stack, so this limit is enforced, not merely documented.

## Agreement — both reject

Confirmed so the generator does not waste refinement rounds "fixing" behaviour
that is already correct: `01` (leading zero), `+1`, `.5`, `Infinity`, `NaN`,
`0x10`, `{a:1}` (unquoted key), `{'a':1}` (single quotes), raw newline/tab inside
a string, `"\x"` (invalid escape), `"\u00"` (short escape), whitespace-only input,
`[,]`, `[1,,]` (double trailing comma — only a *single* trailing comma is
tolerated).

## What this means for the generator

1. **Bias toward the superset rows.** Trailing commas and trailing garbage are
   accepted, which means real parsing work happens on input the formal grammar
   calls invalid. A strictly grammar-conformant generator never exercises it.
2. **Do not over-produce the subset rows.** Duplicate keys and lone surrogates
   are listed in the assignment's edge-case list, but against *this* target they
   are guaranteed rejections. They are worth emitting at low frequency to
   exercise the error path, not as a headline strategy.
3. **Nest deep but under ~2048.** Depth is free structural variety right up to
   the wall; past it every example is an immediate rejection.
4. **Byte-level, not codepoint-level.** parson does not validate UTF-8, so raw
   high bytes inside strings reach the parser proper. That is a genuinely
   under-tested surface and the encoding boundary is where a byte-oriented C
   parser is most likely to go wrong.
