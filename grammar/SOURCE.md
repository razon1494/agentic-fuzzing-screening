# Grammar provenance

| | |
|---|---|
| File | [`JSON.g4`](JSON.g4) |
| Upstream | [antlr/grammars-v4](https://github.com/antlr/grammars-v4), path `json/JSON.g4` |
| Pinned commit | `e1c222f3f0e7c1b2fec799e94e34fc388b03f887` |
| Retrieved | 2026-08-13 |
| Provenance | Derived from <https://json.org>; the grammar file credits *The Definitive ANTLR 4 Reference* (Terence Parr) |

Fetched verbatim, unmodified:

```bash
curl -sSL https://raw.githubusercontent.com/antlr/grammars-v4/e1c222f3f0e7c1b2fec799e94e34fc388b03f887/json/JSON.g4 \
  -o grammar/JSON.g4
```

## Why this grammar

parson implements JSON, and this is grammars-v4's JSON grammar — the assignment's
named starting point. It is small enough (77 lines, 5 parser rules) to hand to an
LLM whole rather than in excerpt, which matters: the seed prompt can contain the
complete language definition instead of a summary that might drop a production.

The recursive structure the generated Hypothesis strategy has to reproduce is
`value → obj | arr`, `obj → pair* → value`, `arr → value*`. That mutual recursion
through `value` is what `st.recursive`/`@composite` must express rather than
flatten — flattening it is the specific failure mode the assignment calls out.

## Target being tested against

| | |
|---|---|
| Library | [kgabis/parson](https://github.com/kgabis/parson) |
| Pinned commit | `ba29f4eda9ea7703a9f6a9cf2b0532a2605723c3` |
| Entry point | `json_parse_string(const char *)` — returns `NULL` on parse failure |
| Fetched by | [`target/build.sh`](../target/build.sh) into gitignored `targets/` |

Chosen from the assignment's list because its own Constraints section reports a
trial run of this exercise on parson/JSON, which makes it the target whose
difficulty is calibrated to the 5-iteration budget.

Where the two disagree — and they do, in both directions — see
[`ADAPTATIONS.md`](ADAPTATIONS.md).
