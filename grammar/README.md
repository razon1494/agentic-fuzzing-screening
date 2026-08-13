# grammar/

Step 1 deliverable — done.

- [`JSON.g4`](JSON.g4) — grammars-v4's JSON grammar, fetched verbatim at a pinned commit.
- [`SOURCE.md`](SOURCE.md) — provenance: upstream commit, retrieval command, and why this grammar and
  this target were chosen.
- [`ADAPTATIONS.md`](ADAPTATIONS.md) — the gap between the formal grammar and parson's real accepted
  language. Twelve differences in both directions, each measured against the sanitizer build rather
  than inferred from reading parser source, plus the exact nesting wall found by bisection.

The last file is the one that matters for the agentic loop: it is what the seed prompt uses to tell
the LLM where the interesting code paths are (parson's superset) and where examples would be wasted
(its subset).
