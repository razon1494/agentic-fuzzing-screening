#!/usr/bin/env python3
"""Step 3 -- baseline strategy and end-to-end pipeline demonstration.

    ~/.venvs/fuzz/bin/python run_baseline.py

Two strategies run against the toy target:

``naive_text``  the actual Step 3 deliverable. Uniform random text, no grammar
                knowledge at all. It is *supposed* to find nothing: its job is
                to prove generate -> serialize -> run -> classify -> log works,
                and to establish the acceptance-rate floor that a
                grammar-seeded generator has to beat.

``smoke_text``  not a deliverable. Just enough structure to actually trip the
                toy's planted bugs, so the crash/dedup/shrink path is exercised
                rather than merely defined.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from hypothesis import strategies as st  # noqa: E402

from fuzzer.campaign import CampaignResult, minimize_all, run_campaign  # noqa: E402
from fuzzer.coverage import production, record_production  # noqa: E402
from fuzzer.runner import HarnessRunner  # noqa: E402

HARNESS = REPO_ROOT / "spine_check" / "build" / "toy_parser"
EXAMPLES = 200
TIMEOUT_S = 1.0


@st.composite
def naive_text(draw) -> str:
    """Uniform random text. Deliberately knows nothing about the grammar."""
    record_production("naive_text")
    return draw(st.text(min_size=0, max_size=64))


@st.composite
def smoke_text(draw) -> str:
    """Minimal structure-aware generator, purely to exercise the crash path."""
    with production("expr"):
        kind = draw(st.sampled_from(["atom", "number", "list"]))

        if kind == "atom":
            record_production("atom")
            return draw(st.text(alphabet="abcxyz", min_size=1, max_size=30))

        if kind == "number":
            record_production("number")
            return draw(st.text(alphabet="0123456789", min_size=1, max_size=14))

        with production("list"):
            body = draw(st.text(alphabet="ab 12~", min_size=0, max_size=8))
            return f"({body})"


def report(label: str, result: CampaignResult) -> None:
    print(f"\n{'=' * 68}\n{label}\n{'=' * 68}")
    print(result.summary())

    if result.rejection_messages:
        unique = sorted(set(result.rejection_messages))[:3]
        print(f"sample_rejections={unique}")

    if not result.crashes:
        print("no crashes -- expected for the naive baseline")
        return

    for record in result.crashes.values():
        print(f"\n  {record.signature.describe()}")
        print(f"  hits={record.hit_count}  first_input={record.first_input!r}")
        if record.minimized is None:
            print("  minimized: NOT REPRODUCED (crash is rare; reproducer unreliable)")
        else:
            print(f"  minimized: {record.minimized!r}  ({len(record.minimized)} chars)")


def main() -> int:
    if not HARNESS.exists():
        print(f"missing {HARNESS}\nrun ./spine_check/build_toy.sh first")
        return 2

    runner = HarnessRunner(HARNESS, timeout_s=TIMEOUT_S)

    baseline = run_campaign(naive_text(), runner, max_examples=EXAMPLES)
    minimize_all(naive_text(), runner, baseline, max_examples=EXAMPLES)
    report("BASELINE (Step 3): naive random text", baseline)

    smoke = run_campaign(smoke_text(), runner, max_examples=EXAMPLES)
    minimize_all(smoke_text(), runner, smoke, max_examples=EXAMPLES)
    report("SMOKE: structure-aware, exercises crash + shrink path", smoke)

    print(
        f"\n{'=' * 68}\n"
        f"pipeline OK: {baseline.total + smoke.total} inputs executed, "
        f"{baseline.bug_count} baseline / {smoke.bug_count} smoke unique signatures"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
