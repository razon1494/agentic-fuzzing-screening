"""Builds the prompt sent to the LLM: grammar in, strategy contract out.

Parameterized by TargetConfig so the same code drives json-parson and
toml-tomlc99 without duplicating anything.

The grammar goes in whole rather than summarized -- summarizing risks silently
dropping a production. The measured grammar/reality gaps go in right beside it,
or the model wastes examples on inputs the library always rejects. And the
grammar sits ahead of a cache breakpoint, since it's identical across
iterations and there's no reason to pay full price for it more than once.
"""

from __future__ import annotations

from .targets import TargetConfig

_CONTRACT_TEMPLATE = '''\
Write a Python module that generates strings in the language of the {format_name}
grammar above, for fuzzing the {library_name} C library with Hypothesis.

## Hard requirements

The module must define exactly this entry point:

    def {entry_name}() -> SearchStrategy[str]

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
    def some_container(draw):
        with production("<grammar rule name>"):
            ...

Mark every terminal production with the plain recorder:

    record_production("<grammar rule name>")

Use the grammar's own rule names ({production_list}) so the coverage report
lines up with the grammar the reader has in front of them. A strategy that skips
this reports zero coverage and the loop cannot steer -- treat it as a
correctness requirement, not a nicety.

## Recursion

Express the grammar's recursive structure with `st.recursive` or `st.deferred`
plus `@composite`. Do not flatten it to a fixed nesting depth: a generator that
claims to be recursive but always emits shallow documents is a specific failure
this exercise is checking for.

## Coverage of the format

Reach the edges as well as the middle: empty containers, deep nesting, extreme
and malformed values, escape sequences, and near-valid-but-malformed documents.
Weight them so the parser still accepts a healthy fraction -- a generator
rejected at the front door on 99% of inputs is not testing the parser, it is
testing the tokenizer.
'''


def build_system_blocks(target: TargetConfig) -> list[dict]:
    """Stable prefix: role, grammar, measured gaps, output contract.

    Returned as a list of blocks with a cache breakpoint on the last one. This
    content does not vary across iterations, so every iteration after the first
    reads it from cache instead of paying full input price for the grammar.
    """
    grammar_sections = "\n\n".join(
        f"```antlr\n# {gf.label}\n{gf.path.read_text(encoding='utf-8')}\n```"
        for gf in target.grammar_files
    )
    adaptations = target.adaptations_path.read_text(encoding="utf-8")
    production_list = ", ".join(f'"{p}"' for p in sorted(target.expected_productions))

    contract = _CONTRACT_TEMPLATE.format(
        format_name=target.format_name,
        library_name=target.library_name,
        entry_name=target.strategy_entry_name,
        production_list=production_list,
    )

    body = f"""\
You are writing Hypothesis strategies that generate test inputs for a C {target.format_name}
parser. You are precise about grammars and you write complete, runnable code.

# The formal grammar (ANTLR grammars-v4, commit {target.grammar_commit})

{grammar_sections}

# How the target actually behaves

The target is {target.library_name} at commit {target.library_commit}, reached
through `{target.entry_point}`. Its real accepted language differs from the
grammar above in both directions. These differences were measured against the
sanitizer build, not inferred, and they are where the interesting code paths are.

{adaptations}

# Your task

{contract}"""

    return [
        {
            "type": "text",
            "text": body,
            # Everything above is identical on every iteration. The breakpoint
            # here is what makes later iterations cheap.
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
against the real sanitizer build of the target library.

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
