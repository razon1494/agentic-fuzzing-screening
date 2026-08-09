#!/usr/bin/env python3
"""Proves the runner + triage spine before the real target library is known.

Run from the repository root, after ./spine_check/build_toy.sh:

    python3 spine_check/test_spine.py

Each case pins down one leg of the crash-vs-rejection decision. If any of these
regress, every number the fuzzer reports afterwards is untrustworthy.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fuzzer.outcomes import Outcome  # noqa: E402
from fuzzer.runner import HarnessRunner  # noqa: E402
from fuzzer.triage import signature_for  # noqa: E402

HARNESS = REPO_ROOT / "spine_check" / "build" / "toy_parser"

# Short timeout: the hang case would otherwise burn the full 5s production budget.
TIMEOUT_S = 1.0

CASES = [
    ("valid atom", b"abc", Outcome.ACCEPT),
    ("valid nested list", b"(a (b 12))", Outcome.ACCEPT),
    ("well-formed rejection", b"!!!", Outcome.REJECT),
    ("stack-buffer-overflow", b"a" * 40, Outcome.CRASH),
    ("signed-integer-overflow", b"99999999999", Outcome.CRASH),
    ("infinite loop", b"(~)", Outcome.TIMEOUT),
]


def main() -> int:
    if not HARNESS.exists():
        print(f"harness missing: {HARNESS}\nrun ./spine_check/build_toy.sh first")
        return 2

    runner = HarnessRunner(HARNESS, timeout_s=TIMEOUT_S)
    failures = 0

    for name, payload, expected in CASES:
        result = runner.run(payload)
        ok = result.outcome is expected
        failures += not ok

        print(f"{'PASS' if ok else 'FAIL'}  {name:<26} {result.summary()}")
        if not ok:
            print(f"      expected {expected.value}, got {result.outcome.value}")

        if signature := signature_for(result):
            print(f"      {signature.describe()}")

    print()
    print(f"{len(CASES) - failures}/{len(CASES)} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
