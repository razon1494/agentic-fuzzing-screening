# grammar/toml-tomlc99/

Step 1 deliverable for the TOML / tomlc99 target — done.

- [`TomlParser.g4`](TomlParser.g4), [`TomlLexer.g4`](TomlLexer.g4) — grammars-v4's split TOML grammar,
  fetched verbatim at the same pinned grammars-v4 commit used for the JSON target.
- [`SOURCE.md`](SOURCE.md) — provenance and why TOML/tomlc99 was chosen as a second target.
- [`ADAPTATIONS.md`](ADAPTATIONS.md) — measured grammar/reality gaps, headlined by a **real
  stack-overflow bug**: tomlc99 has no nesting-depth cap, and deep enough nested arrays or inline
  tables blow the C stack. Found during Step 1 probing, before the agentic loop ran.

This target was added after the JSON/parson run found no crashes, specifically to demonstrate that
`fuzzer/` (outcomes, runner, triage, coverage, campaign) is genuinely target-independent — nothing in
that directory changed to support this second target.
