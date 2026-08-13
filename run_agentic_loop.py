#!/usr/bin/env python3
"""Steps 4 and 5: run the agentic loop, then triage what it found.

    ~/.venvs/fuzz/bin/python run_agentic_loop.py

Requires ./target/build.sh to have been run, and ANTHROPIC_API_KEY to be set
(export it, or put it in .env -- see .env.example).

Steps 4 and 5 are one entrypoint on purpose. Triage needs the campaign's crash
records, and those only exist in memory while the loop is running; splitting the
two would mean serializing every crash to disk and reading it back for no gain.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from fuzzer.agent.client import StrategyAuthor  # noqa: E402
from fuzzer.agent.loop import Iteration, LoopResult, run_loop  # noqa: E402
from fuzzer.runner import HarnessRunner  # noqa: E402

HARNESS = REPO_ROOT / "target" / "build" / "parson_harness"
STRATEGIES_DIR = REPO_ROOT / "strategies"
LOGS_DIR = REPO_ROOT / "logs"
CRASHES_DIR = REPO_ROOT / "crashes"


def main() -> int:
    if not HARNESS.exists():
        print(f"harness missing: {HARNESS}\nrun ./target/build.sh first")
        return 2

    runner = HarnessRunner(HARNESS)
    author = StrategyAuthor()

    outcome = run_loop(runner, author, STRATEGIES_DIR, LOGS_DIR)
    _report(outcome, author)

    if best := outcome.best:
        _write_final_strategy(best)
        written = _write_crashes(runner, best)
        print(f"\ncrash artifacts written: {written}")
    else:
        print("\nno usable iteration -- nothing to triage")

    return 0


def _report(outcome: LoopResult, author: StrategyAuthor) -> None:
    print(f"\n{'=' * 68}\nLOOP COMPLETE ({outcome.stop_reason})\n{'=' * 68}")

    for iteration in outcome.iterations:
        if iteration.result is None:
            print(f"  iteration {iteration.index}: strategy did not run")
            continue
        result = iteration.result
        print(
            f"  iteration {iteration.index}: "
            f"accept={result.acceptance_rate:.1%} "
            f"depth<={max(result.depth_histogram, default=0)} "
            f"productions={len(result.productions_seen)} "
            f"bugs={result.bug_count}"
        )

    print(f"\n{author.ledger()}")


def _write_final_strategy(best: Iteration) -> None:
    """Copy the winning iteration to a stable name for the report to cite."""
    final = STRATEGIES_DIR / "final.py"
    final.write_text(
        f"# Final strategy: iteration {best.index}, "
        f"{best.result.bug_count} unique crash signature(s).\n"
        f"# Verbatim copy of {best.strategy_path.name}; see logs/ for how it evolved.\n\n"
        + best.strategy_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    print(f"\nfinal strategy: iteration {best.index} -> strategies/final.py")


def _write_crashes(runner: HarnessRunner, best: Iteration) -> int:
    """Step 5: one directory per unique signature, verified before it is kept.

    Verification is the point of re-running here. A minimized input that does not
    reproduce standalone is not a reproducer, and reporting one would waste the
    reader's time -- so the re-run's verdict is recorded either way rather than
    quietly assumed.
    """
    result = best.result
    if result is None or not result.crashes:
        _write_none_found(best)
        return 0

    CRASHES_DIR.mkdir(exist_ok=True)
    written = 0

    for signature_id, record in result.crashes.items():
        directory = CRASHES_DIR / signature_id
        directory.mkdir(exist_ok=True)

        reproducer = (
            record.minimized.encode("utf-8", errors="surrogatepass")
            if record.minimized is not None
            else record.first_input
        )
        (directory / "input.bin").write_bytes(reproducer)
        (directory / "sanitizer_report.txt").write_text(record.stderr, encoding="utf-8")

        verified = runner.run(reproducer)
        (directory / "notes.md").write_text(
            "\n".join(
                [
                    f"# {record.signature.bug_class}",
                    "",
                    f"- signature: `{signature_id}`",
                    f"- frames: {' <- '.join(record.signature.frames) or '<none symbolized>'}",
                    f"- hits during the run: {record.hit_count}",
                    f"- minimized: {'yes' if record.minimized is not None else 'NO -- crash too rare to re-reach; first-seen input kept instead'}",
                    f"- reproducer size: {len(reproducer)} bytes",
                    f"- found by: strategies/iteration_{best.index}.py",
                    "",
                    "## Standalone verification",
                    "",
                    f"Re-ran `input.bin` against the pinned build: **{verified.outcome.value}**"
                    f" ({verified.summary().strip()}).",
                    "",
                    "Reproduces deterministically."
                    if verified.outcome.is_bug
                    else "**Did not reproduce.** Treat this signature as unconfirmed.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        written += 1

    return written


def _write_none_found(best: Iteration) -> None:
    """The assignment's documented fallback when a campaign finds nothing."""
    CRASHES_DIR.mkdir(exist_ok=True)
    result = best.result
    (CRASHES_DIR / "NONE_FOUND.md").write_text(
        "\n".join(
            [
                "# No crashes found",
                "",
                f"Best iteration: {best.index} (`strategies/iteration_{best.index}.py`).",
                "",
                "```",
                result.summary() if result else "no campaign completed",
                "```",
                "",
                "See `report/report.md` for what this run covered, which parts of the",
                "grammar are still under-tested, and what would be tried next.",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
