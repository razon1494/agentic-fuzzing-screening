"""Outcome vocabulary shared by the runner, the triage pipeline and the loop.

The single most important judgment call in this project lives here: what counts
as a crash versus a legitimate rejection.  A parser saying "this is not valid
JSON" is the parser working correctly; a parser reading past the end of a buffer
is a bug.  Conflating them poisons every downstream number.
"""

from __future__ import annotations

import signal
from dataclasses import dataclass
from enum import Enum


class Outcome(str, Enum):
    """How a single harness invocation ended."""

    ACCEPT = "accept"
    """Harness exited 0: the library parsed the input successfully."""

    REJECT = "reject"
    """Harness exited with REJECT_EXIT_CODE: a well-formed parse failure."""

    CRASH = "crash"
    """Fatal signal or sanitizer report. A real memory-safety/UB bug."""

    TIMEOUT = "timeout"
    """Exceeded the per-run wall clock. Counts as a crash (see Constraints)."""

    HARNESS_ERROR = "harness_error"
    """Unexpected exit code. The harness itself is wrong, not the library."""

    @property
    def is_bug(self) -> bool:
        """Timeouts count as crashes for grading: a hang is a DoS bug."""
        return self in (Outcome.CRASH, Outcome.TIMEOUT)


REJECT_EXIT_CODE = 1
"""Exit code the C harness uses for a well-formed rejection.

Chosen to be distinguishable from 0 (accept). Note this collides with
AddressSanitizer's *default* exit code, which is why the runner forces
`abort_on_error=1` so sanitizer failures arrive as SIGABRT instead. See
``fuzzer.runner.SANITIZER_ENV``.
"""

SANITIZER_MARKERS = (
    "AddressSanitizer",
    "UndefinedBehaviorSanitizer",
    "LeakSanitizer",
    "runtime error:",
)
"""Substrings whose presence in stderr means a sanitizer fired.

``runtime error:`` is UBSan's terse non-fatal form. We build with
``-fno-sanitize-recover=all`` so it should always be accompanied by an abort,
but we match on it anyway as a belt-and-braces check: a UB report that somehow
exited 0 must never be silently scored as a clean parse.
"""


@dataclass(frozen=True)
class RunResult:
    """Immutable record of one harness invocation."""

    outcome: Outcome
    input_bytes: bytes
    exit_code: int | None
    term_signal: int | None
    stderr: str
    duration_s: float

    @property
    def signal_name(self) -> str | None:
        if self.term_signal is None:
            return None
        try:
            return signal.Signals(self.term_signal).name
        except ValueError:
            return f"SIG{self.term_signal}"

    def summary(self) -> str:
        """One-line form for the iteration log."""
        detail = self.signal_name or f"exit={self.exit_code}"
        return f"{self.outcome.value:<14} {detail:<10} {self.duration_s * 1000:6.1f}ms"
