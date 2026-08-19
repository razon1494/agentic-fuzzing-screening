#!/usr/bin/env python3
"""Steps 4 and 5: run the agentic loop, then triage what it found.

    ~/.venvs/fuzz/bin/python run_agentic_loop.py --target json-parson
    ~/.venvs/fuzz/bin/python run_agentic_loop.py --target toml-tomlc99

Requires the target's ./target/<slug>/build.sh to have been run, and
ANTHROPIC_API_KEY to be set (export it, or put it in .env -- see .env.example).

Steps 4 and 5 share an entrypoint since triage needs the campaign's crash
records, which only exist in memory while the loop is running -- splitting
these would mean serializing every crash to disk just to read it back.

Target is a CLI arg, not a hardcoded path: everything below this line is the
same code for every target, only fuzzer/agent/targets.py differs between them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from fuzzer.agent.client import StrategyAuthor  # noqa: E402
from fuzzer.agent.loop import Iteration, LoopResult, run_loop  # noqa: E402
from fuzzer.agent.targets import TargetConfig, get_target  # noqa: E402
from fuzzer.runner import HarnessRunner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default="json-parson",
        help="target slug from fuzzer/agent/targets.py (default: json-parson)",
    )
    args = parser.parse_args()

    try:
        target = get_target(args.target)
    except ValueError as exc:
        print(exc)
        return 2

    if not target.harness_path.exists():
        print(f"harness missing: {target.harness_path}\nrun ./target/{target.slug}/build.sh first")
        return 2

    runner = HarnessRunner(target.harness_path)
    author = StrategyAuthor()

    print(f"target: {target.slug} ({target.library_name} @ {target.library_commit})")
    outcome = run_loop(runner, author, target, target.strategies_dir, target.logs_dir)
    _report(outcome, author)

    if best := outcome.best:
        _write_final_strategy(target, best)
        written = _write_crashes(runner, target, outcome, best)
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


def _write_final_strategy(target: TargetConfig, best: Iteration) -> None:
    """Copy the winning iteration to a stable name for the report to cite."""
    final = target.strategies_dir / "final.py"
    final.write_text(
        f"# Final strategy: iteration {best.index}, "
        f"{best.result.bug_count} unique crash signature(s).\n"
        f"# Verbatim copy of {best.strategy_path.name}; see logs/{target.slug}/ for how it evolved.\n\n"
        + best.strategy_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    print(f"\nfinal strategy: iteration {best.index} -> strategies/{target.slug}/final.py")


def _write_crashes(
    runner: HarnessRunner,
    target: TargetConfig,
    outcome: LoopResult,
    best: Iteration,
) -> int:
    """One directory per unique signature, verified before it's kept.

    Covers every signature the whole run found, not just the best iteration's,
    so a bug that only ever appeared in an earlier round still gets reported.

    A minimized input that doesn't reproduce standalone isn't a real
    reproducer, so the re-run's verdict gets recorded either way instead of
    just assumed.
    """
    if not outcome.all_crashes:
        _write_none_found(target, best)
        return 0

    target.crashes_dir.mkdir(parents=True, exist_ok=True)
    written = 0

    for signature_id, record in outcome.all_crashes.items():
        directory = target.crashes_dir / signature_id
        directory.mkdir(exist_ok=True)

        reproducer = (
            record.minimized.encode("utf-8", errors="surrogatepass")
            if record.minimized is not None
            else record.first_input
        )
        (directory / "input.bin").write_bytes(reproducer)

        verified = runner.run(reproducer)

        # Two different inputs can be involved: the survey input that first hit
        # the signature, and the (possibly shrunk) one saved as input.bin. Keep
        # both reports and say which is which, rather than filing the survey
        # report next to a reproducer it was not produced by.
        (directory / "sanitizer_report.txt").write_text(
            "# Sanitizer output from the FIRST input that hit this signature\n"
            "# during the survey pass. If `minimized: yes` below, this is not\n"
            "# the same input as input.bin -- see verification_stderr.txt for\n"
            "# the report belonging to input.bin itself.\n\n" + record.stderr,
            encoding="utf-8",
        )
        (directory / "verification_stderr.txt").write_text(
            f"# Standalone re-run of input.bin against the pinned build.\n"
            f"# outcome={verified.outcome.value} exit={verified.exit_code} "
            f"signal={verified.signal_name}\n\n" + verified.stderr,
            encoding="utf-8",
        )

        origin = outcome.crash_origin.get(signature_id, best.index)
        (directory / "notes.md").write_text(
            "\n".join(
                [
                    f"# {record.signature.bug_class}",
                    "",
                    f"- signature: `{signature_id}`",
                    f"- frames: {' <- '.join(record.signature.frames) or '<none symbolized>'}",
                    f"- hits across the run (all iterations): {record.hit_count}",
                    f"- minimized: {'yes' if record.minimized is not None else 'NO -- crash too rare to re-reach; first-seen input kept instead'}",
                    f"- reproducer size: {len(reproducer)} bytes",
                    f"- first found by: strategies/{target.slug}/iteration_{origin}.py",
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
                    "`sanitizer_report.txt` is the survey-pass report for the first input"
                    " that hit this signature; `verification_stderr.txt` is the report for"
                    " `input.bin` as submitted.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        written += 1

    return written


def _write_none_found(target: TargetConfig, best: Iteration) -> None:
    """The assignment's documented fallback when a campaign finds nothing."""
    target.crashes_dir.mkdir(parents=True, exist_ok=True)
    result = best.result
    (target.crashes_dir / "NONE_FOUND.md").write_text(
        "\n".join(
            [
                "# No crashes found",
                "",
                f"Target: {target.library_name} @ {target.library_commit}.",
                f"Best iteration: {best.index} (`strategies/{target.slug}/iteration_{best.index}.py`).",
                "",
                "```",
                result.summary() if result else "no campaign completed",
                "```",
                "",
                "See the written report for what this run covered, which parts of the",
                "grammar are still under-tested, and what would be tried next.",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
