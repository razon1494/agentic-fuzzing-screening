"""The agentic loop: seed -> validate -> run -> summarize -> refine, under budget.

This is where the assignment's central question gets answered. There is no
coverage signal, so something else has to tell the loop whether the generator is
getting better. The signal used here has three parts, and the loop optimizes for
all three at once:

  acceptance rate       is the parser even looking at these inputs? Near zero and
                        nothing past the tokenizer is under test; near one and
                        the error paths never run.
  production coverage   which grammar rules has the generator actually emitted?
                        Unexercised productions are grammar that is provably
                        untested, and pointing the model at them is the most
                        direct lever available.
  nesting depth         did the recursion actually recurse? A generator can
                        satisfy every other check and still emit only flat
                        documents, which is the specific failure the assignment
                        warns about.

Crash signatures found so far ride along, so the model steers away from bugs
already banked instead of re-finding them.

A note on running model-authored code: each iteration writes a Python module and
imports it. The code comes from our own API call on our own machine, which is the
design the assignment specifies, but it is still unreviewed code executing with
full privileges -- worth knowing before pointing this at anything that matters.
"""

from __future__ import annotations

import importlib.util
import traceback
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from hypothesis import strategies as st
from hypothesis.errors import NonInteractiveExampleWarning

from ..campaign import CampaignResult, minimize_all, run_campaign
from ..runner import HarnessRunner
from .client import BudgetExhausted, StrategyAuthor
from .prompts import build_system_blocks, refine_prompt, seed_prompt
from .targets import TargetConfig

MAX_ITERATIONS = 5
"""Iteration cap from the assignment's Constraints section."""

EXAMPLES_PER_ITERATION = 500
"""Per-run example cap, likewise from Constraints."""

VALIDATION_SAMPLE = 12
"""How many examples to spot-check before spending a whole run on a strategy.

Small on purpose: this is a smoke test for "did the model emit something that
draws at all", not a statistical claim. The real quality signal is the
acceptance rate over the full run.
"""


@dataclass
class Iteration:
    """One trip around the loop, kept for the evolution log."""

    index: int
    rationale: str
    changes: tuple[str, ...]
    strategy_path: Path
    cost_usd: float
    result: CampaignResult | None = None
    load_error: str | None = None

    @property
    def usable(self) -> bool:
        return self.result is not None


@dataclass
class LoopResult:
    """Everything the report needs about how the generator evolved."""

    iterations: list[Iteration] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    stop_reason: str = "iteration cap"

    @property
    def best(self) -> Iteration | None:
        """The iteration that found the most distinct bugs, ties going to later."""
        usable = [it for it in self.iterations if it.usable]
        if not usable:
            return None
        return max(usable, key=lambda it: (it.result.bug_count, it.index))


class StrategyLoadError(RuntimeError):
    """The generated module did not import, or did not expose the entry point."""


def run_loop(
    runner: HarnessRunner,
    author: StrategyAuthor,
    target: TargetConfig,
    strategies_dir: Path,
    logs_dir: Path,
    max_iterations: int = MAX_ITERATIONS,
    max_examples: int = EXAMPLES_PER_ITERATION,
) -> LoopResult:
    """Drive the loop until the iteration cap or the budget stops it."""
    strategies_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    system_blocks = build_system_blocks(target)
    outcome = LoopResult()
    current_code = ""
    feedback = ""

    for index in range(max_iterations):
        prompt = seed_prompt() if index == 0 else refine_prompt(current_code, feedback)

        try:
            proposal = author.propose(system_blocks, prompt)
        except BudgetExhausted as exhausted:
            outcome.stop_reason = f"budget exhausted: {exhausted}"
            break

        current_code = proposal.strategy_code
        strategy_path = strategies_dir / f"iteration_{index}.py"
        strategy_path.write_text(current_code, encoding="utf-8")

        iteration = Iteration(
            index=index,
            rationale=proposal.rationale,
            changes=proposal.changes,
            strategy_path=strategy_path,
            cost_usd=proposal.usage.cost_usd,
        )
        print(f"\n=== iteration {index} === {proposal.usage.summary()}")

        try:
            strategy = _load_strategy(strategy_path, target.strategy_entry_name)
            _validate_generator(strategy)
        except StrategyLoadError as broken:
            # A broken module is not a dead end -- it is feedback. Hand the model
            # its own traceback and let the next iteration repair it, rather than
            # aborting a run that still has budget left.
            iteration.load_error = str(broken)
            feedback = _load_failure_feedback(broken)
            outcome.iterations.append(iteration)
            _write_log(logs_dir, iteration, feedback)
            print(f"  strategy unusable: {str(broken).splitlines()[0]}")
            continue

        result = run_campaign(strategy, runner, max_examples=max_examples)
        minimize_all(strategy, runner, result, max_examples=max_examples)
        iteration.result = result
        feedback = summarize_for_llm(result, target)

        outcome.iterations.append(iteration)
        _write_log(logs_dir, iteration, feedback)
        print(f"  {result.summary().splitlines()[1]}  bugs={result.bug_count}")

    outcome.total_cost_usd = author.spent_usd
    outcome.total_tokens = author.total_tokens
    return outcome


def summarize_for_llm(result: CampaignResult, target: TargetConfig) -> str:
    """The compact digest the model refines against -- the loop's steering signal.

    Deliberately small. Everything here is something the model can act on; raw
    per-input logs would cost tokens on every iteration and tell it nothing it
    could not infer from the aggregate.
    """
    missing = sorted(target.expected_productions - result.productions_seen)
    unexpected = sorted(result.productions_seen - target.expected_productions)

    lines = [
        result.summary(),
        f"acceptance_verdict: {_acceptance_verdict(result.acceptance_rate)}",
        f"productions_never_exercised: {missing or 'none'}",
        f"depth_verdict: {_depth_verdict(result.depth_histogram)}",
    ]

    if unexpected:
        lines.append(
            f"productions_recorded_under_unrecognized_names: {unexpected} "
            "(use the grammar's own rule names so coverage lines up)"
        )

    if result.crashes:
        lines.append("\ncrash signatures found so far (do not re-target these):")
        for record in result.crashes.values():
            reproducer = record.minimized if record.minimized is not None else "<not reproduced>"
            lines.append(
                f"  [{record.signature.signature_id}] {record.signature.bug_class} "
                f"x{record.hit_count}  minimized={reproducer!r}"
            )
    else:
        lines.append("\nno crashes yet")

    if result.rejection_messages:
        sample = sorted(set(result.rejection_messages))[:5]
        lines.append(f"\nsample parser rejections: {sample}")

    return "\n".join(lines)


def _acceptance_verdict(rate: float) -> str:
    """Turn the rate into the judgment the model should act on."""
    if rate < 0.05:
        return (
            f"{rate:.1%} -- CRITICAL. Almost nothing parses; the parser proper is "
            "not being reached. Fix generator correctness before anything else."
        )
    if rate < 0.30:
        return f"{rate:.1%} -- low. Much of the budget is spent on inputs rejected at the front door."
    if rate > 0.95:
        return (
            f"{rate:.1%} -- too high. Only well-formed documents are being emitted, "
            "so parser error handling is untested. Add near-valid malformed inputs."
        )
    return f"{rate:.1%} -- healthy: a real mix of accepted and rejected inputs."


def _depth_verdict(histogram: Counter) -> str:
    """Catch a 'recursive' generator that never actually recurses."""
    if not histogram:
        return "no depth recorded -- the strategy is not using production() at all"

    deepest = max(histogram)
    total = sum(histogram.values())
    shallow = sum(count for depth, count in histogram.items() if depth <= 1)

    if deepest <= 1:
        return f"max depth {deepest} -- the recursion is nominal; nothing nests"
    if shallow / total > 0.8:
        return (
            f"max depth {deepest}, but {shallow / total:.0%} of documents are depth<=1 "
            "-- deep nesting is rare enough to be nearly untested"
        )
    return f"max depth {deepest}, with a real spread across depths"


def _load_failure_feedback(broken: StrategyLoadError) -> str:
    return (
        "Your module did not run. It was never executed against the target, so "
        "there are no results this iteration.\n\n"
        f"```\n{broken}\n```\n\n"
        "Return a corrected, complete module. Check that every name you use is "
        "imported and that the entry point is defined exactly as the contract "
        "requires."
    )


def _load_strategy(path: Path, entry_name: str) -> st.SearchStrategy[str]:
    """Import the generated module and pull out its entry point."""
    spec = importlib.util.spec_from_file_location(f"generated_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise StrategyLoadError(f"cannot import {path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        raise StrategyLoadError(traceback.format_exc(limit=6)) from None

    entry = getattr(module, entry_name, None)
    if entry is None:
        raise StrategyLoadError(
            f"module defines no {entry_name}(); "
            f"found: {sorted(n for n in vars(module) if not n.startswith('_'))}"
        )

    try:
        strategy = entry()
    except Exception:
        raise StrategyLoadError(
            f"{entry_name}() raised:\n{traceback.format_exc(limit=6)}"
        ) from None

    if not isinstance(strategy, st.SearchStrategy):
        raise StrategyLoadError(
            f"{entry_name}() returned {type(strategy).__name__}, "
            "expected a Hypothesis SearchStrategy"
        )
    return strategy


def _validate_generator(strategy: st.SearchStrategy[str]) -> None:
    """Step 4.2: cheap sanity check before spending a full run on this strategy.

    Catches the degenerate cases -- draws that raise, non-string output, a
    generator stuck on one constant -- for the price of a dozen examples. It
    deliberately does *not* judge quality; that is the acceptance rate's job,
    and it needs the real parser to measure.
    """
    samples: list[str] = []
    with warnings.catch_warnings():
        # .example() warns because it is the wrong tool inside a test. Here we
        # are outside the test, spot-checking a generator we did not write.
        warnings.simplefilter("ignore", NonInteractiveExampleWarning)
        for _ in range(VALIDATION_SAMPLE):
            try:
                samples.append(strategy.example())
            except Exception:
                raise StrategyLoadError(
                    f"drawing an example raised:\n{traceback.format_exc(limit=6)}"
                ) from None

    if bad := [s for s in samples if not isinstance(s, str)]:
        raise StrategyLoadError(
            f"strategy produced {type(bad[0]).__name__}, expected str"
        )

    if len(set(samples)) == 1:
        raise StrategyLoadError(
            f"strategy is degenerate: {VALIDATION_SAMPLE} draws all returned "
            f"{samples[0]!r}"
        )


def _write_log(logs_dir: Path, iteration: Iteration, feedback: str) -> None:
    """One markdown file per iteration -- the evolution log the report links to."""
    parts = [
        f"# Iteration {iteration.index}",
        "",
        f"- strategy: `{iteration.strategy_path.name}`",
        f"- cost: ${iteration.cost_usd:.4f}",
        "",
        "## Rationale",
        "",
        iteration.rationale,
    ]

    if iteration.changes:
        parts += ["", "## Changes from the previous iteration", ""]
        parts += [f"- {change}" for change in iteration.changes]

    if iteration.load_error:
        parts += ["", "## Outcome: strategy did not run", "", "```", iteration.load_error, "```"]
    else:
        parts += ["", "## Measured results", "", "```", feedback, "```"]

    (logs_dir / f"iteration_{iteration.index}.md").write_text(
        "\n".join(parts) + "\n", encoding="utf-8"
    )
