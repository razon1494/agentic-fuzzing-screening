# Grammar provenance

| | |
|---|---|
| Files | [`TomlParser.g4`](TomlParser.g4), [`TomlLexer.g4`](TomlLexer.g4) |
| Upstream | [antlr/grammars-v4](https://github.com/antlr/grammars-v4), path `toml/` |
| Pinned commit | `e1c222f3f0e7c1b2fec799e94e34fc388b03f887` (same commit used for `json/JSON.g4`) |
| Retrieved | 2026-08-13 |
| License | Apache License 2.0 (grammar file header) |

Fetched verbatim, unmodified:

```bash
curl -sSL https://raw.githubusercontent.com/antlr/grammars-v4/e1c222f3f0e7c1b2fec799e94e34fc388b03f887/toml/TomlParser.g4 \
  -o grammar/toml-tomlc99/TomlParser.g4
curl -sSL https://raw.githubusercontent.com/antlr/grammars-v4/e1c222f3f0e7c1b2fec799e94e34fc388b03f887/toml/TomlLexer.g4 \
  -o grammar/toml-tomlc99/TomlLexer.g4
```

## Why this grammar

TOML's grammars-v4 entry is a split lexer/parser (298 lines combined), unlike
JSON's single-file grammar. Both files are handed to the LLM whole — splitting
lexer tokens from parser rules is exactly the boundary an LLM strategy author
needs to reproduce (which productions are terminals vs. recursive rules).

The structure a generated Hypothesis strategy has to reproduce is deeper than
JSON's: `value → array_ | inline_table`, `array_ → value*`,
`inline_table → key_value*`, and `table`/`array_table` headers that open a new
nesting scope for subsequent `key_value` lines outside the `{}`/`[]` delimiters
entirely — TOML's "dotted key" and "table header" forms have no JSON analogue.

## Target being tested against

| | |
|---|---|
| Library | [cktan/tomlc99](https://github.com/cktan/tomlc99) |
| Pinned commit | `29076dfd095bbbbd50a3c1b2760d29f4b83e74ac` |
| Entry point | `toml_parse(char *conf, char *errbuf, int errbufsz)` — returns `NULL` on parse failure, error text in `errbuf` |
| Fetched by | [`target/toml-tomlc99/build.sh`](../../target/toml-tomlc99/build.sh) into gitignored `targets/` |

Chosen as the second target after `json-parson` found no crashes: the `fuzzer/`
spine (outcomes, runner, triage, coverage, campaign) is target-independent by
design, and TOML's richer, more recursive grammar (nested inline tables, array
tables, dotted keys) is a plausible place to find what JSON/parson did not.
tomlc99's source has **no explicit nesting-depth cap** (unlike parson's
`MAX_NESTING 2048`) — a candidate for a stack-overflow bug via unbounded
recursion, worth probing carefully rather than assuming.

Where the grammar and tomlc99 disagree — see
[`ADAPTATIONS.md`](ADAPTATIONS.md).
