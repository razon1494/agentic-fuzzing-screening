"""The Anthropic call, and the token/cost ledger the final report has to show.

The assignment caps the loop at "5 iterations or roughly $5 of LLM API spend,
whichever comes first" and asks for both numbers in the report. That makes the
ledger a deliverable rather than instrumentation, so it lives here rather than
being bolted on: every call updates a running total, and the budget is enforced
*before* a request is sent, not discovered afterwards.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-5"
"""Which model authors the strategy.

The assignment's budget note assumes "small/mid-tier model pricing" for the
5-iteration loop, and Sonnet fits that at roughly a third of Opus's per-token
cost while still reading a 77-line grammar and writing a correct recursive
generator reliably. If a run's strategies come back weak (flat recursion,
missed productions) despite clear feedback, switch to `claude-opus-5` here --
nothing else in the loop changes, and the cost ledger below reports whichever
model was actually used.
"""

PRICING_USD_PER_MTOK = {
    # (input, output). Cache writes bill at 1.25x input, cache reads at 0.1x.
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

BUDGET_USD = 5.00
"""Hard spend ceiling from the assignment's Constraints section."""

MAX_TOKENS = 64000
"""Ceiling on thinking *plus* the returned module -- the two share this budget.

Set high on purpose. A truncated response is not a degraded response: the JSON
stops mid-string and the whole iteration is lost, having already been billed.
16000 was tried first and was not enough once adaptive thinking was included.
This is a cap rather than a spend, so unused headroom costs nothing.
"""

# The LLM returns this shape rather than a fenced code block. Parsing a fence
# means regexing model prose, which fails the first time the model wraps its
# answer differently; a schema makes malformed output a 400 from the API instead
# of a mystery `None` three stack frames later.
_PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "strategy_code": {
            "type": "string",
            "description": "Complete, runnable Python module source.",
        },
        "rationale": {
            "type": "string",
            "description": "Why this design generates the grammar's language.",
        },
        "changes": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "What changed from the previous iteration and which signal "
                "motivated it. Empty list on the seed iteration."
            ),
        },
    },
    "required": ["strategy_code", "rationale", "changes"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Usage:
    """Token counts for one call, priced at the model's public rates."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        """Estimated dollar cost. Cache multipliers are the published ones."""
        rate_in, rate_out = PRICING_USD_PER_MTOK.get(self.model, (0.0, 0.0))
        billable_input = (
            self.input_tokens
            + self.cache_creation_input_tokens * 1.25
            + self.cache_read_input_tokens * 0.10
        )
        return (billable_input * rate_in + self.output_tokens * rate_out) / 1e6

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    def summary(self) -> str:
        return (
            f"in={self.input_tokens} out={self.output_tokens} "
            f"cache_write={self.cache_creation_input_tokens} "
            f"cache_read={self.cache_read_input_tokens} "
            f"cost=${self.cost_usd:.4f}"
        )


@dataclass(frozen=True)
class Proposal:
    """One strategy the LLM wrote, plus what it cost to get it."""

    strategy_code: str
    rationale: str
    changes: tuple[str, ...]
    usage: Usage


class BudgetExhausted(RuntimeError):
    """Raised before a call that would push spend past the cap."""


class StrategyAuthor:
    """Asks the model for a Hypothesis strategy and tracks what it cost."""

    def __init__(
        self,
        model: str = MODEL,
        budget_usd: float = BUDGET_USD,
        max_tokens: int = MAX_TOKENS,
    ) -> None:
        self.model = model
        self.budget_usd = budget_usd
        self.max_tokens = max_tokens
        self.calls: list[Usage] = []
        self._client = anthropic.Anthropic(api_key=_load_api_key())

    @property
    def spent_usd(self) -> float:
        return sum(call.cost_usd for call in self.calls)

    @property
    def total_tokens(self) -> int:
        return sum(call.total_tokens for call in self.calls)

    def propose(self, system_blocks: list[dict], user_text: str) -> Proposal:
        """One round trip: grammar (+ feedback) in, strategy code out.

        `system_blocks` carries the grammar and adaptations with a cache
        breakpoint on the last block -- that content is byte-identical across all
        five iterations, so every iteration after the first reads it at a tenth
        of the input price. The per-iteration feedback goes in `user_text`,
        *after* the breakpoint, which is what keeps the prefix stable.
        """
        if self.spent_usd >= self.budget_usd:
            raise BudgetExhausted(
                f"spent ${self.spent_usd:.2f} of ${self.budget_usd:.2f} budget"
            )

        # Streaming, because a long strategy at a high max_tokens can otherwise
        # sit past the SDK's HTTP timeout with nothing on the wire.
        with self._client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": _PROPOSAL_SCHEMA}},
            system=system_blocks,
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise RuntimeError(f"model declined: {message.stop_details}")

        # Check this before parsing. A truncated response is still valid-looking
        # text, so json.loads() reports "unterminated string" -- which reads like
        # a parser bug rather than what it is, an exhausted token budget.
        if message.stop_reason == "max_tokens":
            raise RuntimeError(
                f"response truncated at max_tokens={self.max_tokens}; the module "
                "was cut off mid-JSON. Raise MAX_TOKENS."
            )

        usage = Usage(
            model=self.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cache_creation_input_tokens=message.usage.cache_creation_input_tokens or 0,
            cache_read_input_tokens=message.usage.cache_read_input_tokens or 0,
        )
        self.calls.append(usage)

        payload = json.loads(_first_text(message))
        return Proposal(
            strategy_code=payload["strategy_code"],
            rationale=payload["rationale"],
            changes=tuple(payload.get("changes", ())),
            usage=usage,
        )

    def ledger(self) -> str:
        """The cost table the report has to include."""
        lines = [f"model={self.model}  calls={len(self.calls)}"]
        for index, call in enumerate(self.calls):
            lines.append(f"  iteration {index}: {call.summary()}")
        lines.append(
            f"total: {self.total_tokens} tokens, "
            f"${self.spent_usd:.4f} of ${self.budget_usd:.2f} budget"
        )
        return "\n".join(lines)


def _first_text(message: anthropic.types.Message) -> str:
    """The schema guarantees one text block of valid JSON; find it explicitly.

    Indexing content[0] would break the moment a thinking block leads the list,
    which it does whenever adaptive thinking fires.
    """
    for block in message.content:
        if block.type == "text":
            return block.text
    raise RuntimeError(f"no text block in response (stop_reason={message.stop_reason})")


def _load_api_key() -> str:
    """Read the key from the environment, falling back to the gitignored .env.

    Kept out of every log line and every prompt on purpose -- the loop writes
    prompts and responses to logs/, and a key pasted into one would be committed
    the moment someone adds the log to the repo.
    """
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        return key

    env_file = Path(__file__).resolve().parents[2] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "ANTHROPIC_API_KEY":
                if stripped := value.strip().strip("'\""):
                    return stripped

    raise RuntimeError(
        "ANTHROPIC_API_KEY not set. Export it, or copy .env.example to .env "
        "and fill it in (.env is gitignored)."
    )
