"""Grammar-seeded, LLM-refined fuzzing harness.

Layering, bottom up:

    outcomes.py   vocabulary: what counts as a crash vs a rejection
    runner.py     execute the sanitizer build on one input, classify the result
    triage.py     turn a sanitizer report into a dedupable crash signature

Everything above this line is target-independent. The target library only
appears in the C harness and the grammar-derived strategy.
"""

from .outcomes import Outcome, RunResult
from .runner import HarnessRunner
from .triage import CrashSignature, signature_for

__all__ = [
    "CrashSignature",
    "HarnessRunner",
    "Outcome",
    "RunResult",
    "signature_for",
]
