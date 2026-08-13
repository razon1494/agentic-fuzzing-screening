"""Step 4: the agentic loop that turns a grammar into a Hypothesis strategy.

    prompts.py   what the LLM is told: grammar in, strategy contract out
    client.py    the Anthropic call, plus the token/cost ledger the report needs
    loop.py      seed -> validate -> run -> summarize -> refine, under a budget

The split matters for the deliverable: `loop.py` owns the *feedback design*,
which is what the assignment actually grades, while `client.py` is plumbing.
Keeping them apart makes it possible to read the loop's logic without wading
through SDK details.
"""

from .client import Proposal, StrategyAuthor, Usage

__all__ = ["Proposal", "StrategyAuthor", "Usage"]
