# grammar/

Step 1 deliverable, per target. One subdirectory per fuzzing target:

- [`json-parson/`](json-parson/) — JSON grammar, parson target. Original submission.
- [`toml-tomlc99/`](toml-tomlc99/) — TOML grammar, tomlc99 target. Added as a second target after the
  JSON run found no crashes; see its `ADAPTATIONS.md` for a real stack-overflow bug found during
  probing.

Each subdirectory follows the same shape: the grammar file(s) fetched verbatim at a pinned commit,
`SOURCE.md` for provenance, and `ADAPTATIONS.md` for the measured gap between the formal grammar and
the target library's real accepted language — the input the agentic loop's seed prompt is built from.
