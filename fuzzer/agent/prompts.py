"""What the LLM is told. This file *is* the "drive an LLM from a grammar" part.

Three deliberate choices, each with a reason the report can defend:

1. The grammar goes in whole, not summarized. It is 77 lines -- small enough to
   paste, and summarizing it would silently drop productions, which is exactly
   the failure the assignment warns about.
2. The measured grammar/reality gaps go in alongside it. Without them the model
   optimizes for the formal grammar and wastes examples on inputs parson always
   rejects (duplicate keys, lone surrogates) while never reaching the code paths
   past the grammar that parson does accept (trailing commas, trailing garbage).
3. Stable content is a cached system prefix; per-iteration feedback is the user
   turn. The grammar is byte-identical across all five iterations, so keeping it
   ahead of the cache breakpoint makes iterations 2-5 read it at a tenth price.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAMMAR_PATH = REPO_ROOT / "grammar" / "JSON.g4"
ADAPTATIONS_PATH = REPO_ROOT / "grammar" / "ADAPTATIONS.md"

STRATEGY_MODULE_NAME = "json_document"
"""The callable the generated module must expose. The loop imports this by name,
so it is part of the contract rather than a convention."""

_CONTRACT = f'''\
Write a Python module that generates strings in the language of the JSON grammar
above, for fuzzing the parson C library with Hypothesis.

## Hard requirements

The module must define exactly this entry point:

    def {STRATEGY_MODULE_NAME}() -> SearchStrategy[str]

It may define any number of helper strategies. It must be a complete, runnable
module: every import at the top, no ellipses, no "..." placeholders, no prose
outside comments and docstrings.

Available imports (the repository is on sys.path):

    from hypothesis import strategies as st
    from fuzzer.coverage import production, record_production

## Instrumenting productions -- not optional

`fuzzer.coverage` is how this loop gets a feedback signal at all. The assignment
forbids coverage instrumentation of the *target*, so the generator instruments
*itself*: every strategy declares which grammar production it is expanding, and
the loop reads back which productions fired and how deep recursion went.

Wrap every recursive production in the context manager, which also tracks depth:

    @st.composite
    def json_array(draw):
        with production("arr"):
            items = draw(st.lists(json_value(), max_size=4))
            return "[" + ",".join(items) + "]"

Mark every terminal production with the plain recorder:

    record_production("NUMBER")

Use the grammar's own rule names ("obj", "pair", "arr", "value", "STRING",
"NUMBER") so the coverage report lines up with the grammar the reader has in
front of them. A strategy that skips this reports zero coverage and the loop
cannot steer -- treat it as a correctness requirement, not a nicety.

## Recursion

Express the grammar's mutual recursion (`value -> obj | arr -> value`) with
`st.recursive` or `st.deferred` plus `@composite`. Do not flatten it to a fixed
nesting depth: a generator that claims to be recursive but always emits depth-1
documents is a specific failure this exercise is checking for.

## Coverage of the format

Reach the edges as well as the middle: empty containers, deep nesting, duplicate
keys, extreme and malformed numbers, unicode and escape sequences, and
near-valid-but-malformed documents. Weight them so the parser still accepts a
healthy fraction -- a generator rejected at the front door on 99% of inputs is
not testing the parser, it is testing the tokenizer.
'''


def build_system_blocks() -> list[dict]:
    """Stable prefix: role, grammar, measured gaps, output contract.

    Returned as a list of blocks with a cache breakpoint on the last one. This
    content does not vary across iterations, so every iteration after the first
    reads it from cache instead of paying full input price for the grammar.
    """
    grammar = GRAMMAR_PATH.read_text(encoding="utf-8")
    adaptations = ADAPTATIONS_PATH.read_text(encoding="utf-8")

    body = f"""\
You are writing Hypothesis strategies that generate test inputs for a C JSON
parser. You are precise about grammars and you write complete, runnable code.

# The formal grammar (ANTLR grammars-v4, json/JSON.g4, commit e1c222f)

```antlr
{grammar}
```

# How the target actually behaves

The target is parson (kgabis/parson) at commit ba29f4e, reached through
`json_parse_string`. Its real accepted language differs from the grammar above
in both directions. These differences were measured against the sanitizer build,
not inferred, and they are where the interesting code paths are.

{adaptations}

# Your task

{_CONTRACT}"""

    return [
        {
            "type": "text",
            "text": body,
            # Everything above is identical on every iteration. The breakpoint
            # here is what makes iterations 2-5 cheap.
            "cache_control": {"type": "ephemeral"},
        }
    ]


def seed_prompt() -> str:
    """Iteration 0: no feedback exists yet, so ask for the grammar-faithful base."""
    return (
        "Write the first version of the strategy.\n\n"
        "Aim for faithfulness to the grammar and structural variety: correct "
        "recursion, every production reachable, and the edge cases listed in the "
        "contract present but not dominant. Do not try to guess where the bugs "
        "are yet -- later iterations get real feedback for that.\n\n"
        "Set `changes` to an empty list; there is no previous version."
    )


def refine_prompt(current_code: str, feedback: str) -> str:
    """Iterations 1-N: the current strategy plus what the last run measured.

    The feedback block is assembled by `loop.summarize_for_llm`, which decides
    what the model gets to see. That choice -- acceptance rate, unexercised
    productions, depth histogram, rejection samples, crash signatures -- is the
    proxy signal this whole exercise is steering by, since no coverage data
    exists.
    """
    return f"""\
Here is the strategy you wrote last iteration, and what happened when it ran
against the real parson build.

# Current strategy

```python
{current_code}
```

# Results

{feedback}

# What to do

Propose a revised strategy. Read the numbers before you change anything, and let
them pick the change:

- Acceptance rate near zero means the generator is malformed at the tokenizer
  level and nothing past the front door is under test. Fix correctness first;
  everything else is wasted until inputs parse.
- Acceptance rate near one means it only emits well-formed documents and never
  probes error handling. Add near-valid malformed inputs.
- Productions listed as never exercised are grammar the generator cannot reach.
  Reaching them is usually worth more than deepening what already works.
- A depth histogram concentrated at 0-1 means the recursion is nominal. Real
  nesting is where a C parser's recursion handling gets tested.
- Crash signatures already found are done. Steer away from them toward the parts
  of the grammar that have not produced one, rather than re-finding the same bug.

Return the complete module again, not a diff. In `changes`, list each edit with
the specific number that motivated it."""
