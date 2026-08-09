"""Executes the sanitizer-built C harness against one generated input.

This is deliberately target-independent: point it at any harness binary that
follows the exit-code contract in :mod:`fuzzer.outcomes` and it works.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .outcomes import (
    REJECT_EXIT_CODE,
    SANITIZER_MARKERS,
    Outcome,
    RunResult,
)

DEFAULT_TIMEOUT_S = 5.0
"""Per-run timeout from the assignment Constraints section."""

SANITIZER_ENV = {
    # Turn sanitizer findings into SIGABRT. Without this ASan exits with code 1,
    # which is exactly our "well-formed rejection" code -- every memory bug
    # would be silently misfiled as the parser politely saying no.
    "ASAN_OPTIONS": ":".join(
        [
            "abort_on_error=1",
            "symbolize=1",
            # Leaks are real bugs but they are not what this assignment targets,
            # and an allocating parser leaks on nearly every input, which would
            # drown the memory-safety signal. Documented judgment call.
            "detect_leaks=0",
            "allocator_may_return_null=1",
        ]
    ),
    "UBSAN_OPTIONS": ":".join(
        [
            "halt_on_error=1",
            "print_stacktrace=1",
            "abort_on_error=1",
        ]
    ),
}


class HarnessRunner:
    """Runs one input through the harness and classifies the result."""

    def __init__(
        self,
        harness_path: str | Path,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        reject_exit_code: int = REJECT_EXIT_CODE,
    ) -> None:
        self.harness_path = Path(harness_path)
        self.timeout_s = timeout_s
        self.reject_exit_code = reject_exit_code
        if not self.harness_path.exists():
            raise FileNotFoundError(f"harness not built: {self.harness_path}")

    def run(self, data: bytes) -> RunResult:
        """Feed ``data`` to the harness on stdin and classify how it ended."""
        env = {**os.environ, **SANITIZER_ENV}
        started = time.monotonic()

        try:
            proc = subprocess.run(
                [str(self.harness_path)],
                input=data,
                capture_output=True,
                timeout=self.timeout_s,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as expired:
            return RunResult(
                outcome=Outcome.TIMEOUT,
                input_bytes=data,
                exit_code=None,
                term_signal=None,
                stderr=_decode(expired.stderr),
                duration_s=time.monotonic() - started,
            )

        duration = time.monotonic() - started
        stderr = _decode(proc.stderr)
        exit_code, term_signal = _split_status(proc.returncode)

        return RunResult(
            outcome=self._classify(exit_code, term_signal, stderr),
            input_bytes=data,
            exit_code=exit_code,
            term_signal=term_signal,
            stderr=stderr,
            duration_s=duration,
        )

    def _classify(
        self, exit_code: int | None, term_signal: int | None, stderr: str
    ) -> Outcome:
        # Sanitizer output wins over the exit code. A UB report that somehow
        # managed to exit 0 is still a bug, and must not be scored as a parse.
        if any(marker in stderr for marker in SANITIZER_MARKERS):
            return Outcome.CRASH
        if term_signal is not None:
            return Outcome.CRASH
        if exit_code == 0:
            return Outcome.ACCEPT
        if exit_code == self.reject_exit_code:
            return Outcome.REJECT
        return Outcome.HARNESS_ERROR


def _split_status(returncode: int) -> tuple[int | None, int | None]:
    """subprocess encodes death-by-signal as a negative return code."""
    if returncode < 0:
        return None, -returncode
    return returncode, None


def _decode(raw: bytes | None) -> str:
    if not raw:
        return ""
    return raw.decode("utf-8", errors="replace")
