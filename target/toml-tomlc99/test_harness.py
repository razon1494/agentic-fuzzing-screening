#!/usr/bin/env python3
"""Step 2 checkpoint: the harness classifies known-good and known-bad TOML.

Run from the repository root, after ./target/toml-tomlc99/build.sh:

    python3 target/toml-tomlc99/test_harness.py

Structurally identical to target/json-parson/test_harness.py -- see that file's
docstring for the full rationale.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fuzzer.outcomes import Outcome  # noqa: E402
from fuzzer.runner import HarnessRunner  # noqa: E402

HARNESS = HERE / "build" / "tomlc99_harness"
SAMPLES = HERE / "samples"

EXPECTATIONS = (
    (SAMPLES / "valid", Outcome.ACCEPT),
    (SAMPLES / "invalid", Outcome.REJECT),
)


def main() -> int:
    if not HARNESS.exists():
        print(f"harness missing: {HARNESS}\nrun ./target/toml-tomlc99/build.sh first")
        return 2

    runner = HarnessRunner(HARNESS)
    failures = 0
    checked = 0

    for directory, expected in EXPECTATIONS:
        for sample in sorted(directory.glob("*.toml")):
            result = runner.run(sample.read_bytes())
            ok = result.outcome is expected
            failures += not ok
            checked += 1

            label = f"{directory.name}/{sample.name}"
            print(f"{'PASS' if ok else 'FAIL'}  {label:<42} {result.summary()}")

            if not ok:
                print(f"      expected {expected.value}, got {result.outcome.value}")
                if result.stderr:
                    first = result.stderr.strip().splitlines()[0]
                    print(f"      stderr: {first}")

    print(f"\n{checked - failures}/{checked} samples classified correctly")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
