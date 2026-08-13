#!/usr/bin/env python3
"""Step 2 checkpoint: the harness classifies known-good and known-bad JSON.

Run from the repository root, after ./target/build.sh:

    python3 target/test_harness.py

Every sample under samples/valid/ must parse, every sample under samples/invalid/
must be rejected *cleanly* -- exit 1, no sanitizer output, no signal. A sample
that crashes here is not a passing test; it means either the harness is wrong or
we found a bug before the fuzzer even started, and both need looking at before
any campaign number can be trusted.

This deliberately imports nothing from Hypothesis: it is a property of the
harness, not of the generator, and it must stay runnable when the loop is broken.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fuzzer.outcomes import Outcome  # noqa: E402
from fuzzer.runner import HarnessRunner  # noqa: E402

HARNESS = REPO_ROOT / "target" / "build" / "parson_harness"
SAMPLES = REPO_ROOT / "target" / "samples"

EXPECTATIONS = (
    (SAMPLES / "valid", Outcome.ACCEPT),
    (SAMPLES / "invalid", Outcome.REJECT),
)


def main() -> int:
    if not HARNESS.exists():
        print(f"harness missing: {HARNESS}\nrun ./target/build.sh first")
        return 2

    runner = HarnessRunner(HARNESS)
    failures = 0
    checked = 0

    for directory, expected in EXPECTATIONS:
        for sample in sorted(directory.glob("*.json")):
            result = runner.run(sample.read_bytes())
            ok = result.outcome is expected
            failures += not ok
            checked += 1

            label = f"{directory.name}/{sample.name}"
            print(f"{'PASS' if ok else 'FAIL'}  {label:<34} {result.summary()}")

            if not ok:
                print(f"      expected {expected.value}, got {result.outcome.value}")
                if result.stderr:
                    first = result.stderr.strip().splitlines()[0]
                    print(f"      stderr: {first}")

    print(f"\n{checked - failures}/{checked} samples classified correctly")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
