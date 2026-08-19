"""Runs one bounded fuzzing campaign and minimizes whatever it finds.

Hypothesis is used in two distinct passes, and the split matters:

*Survey* runs ``Phase.generate`` only. The test never fails, so Hypothesis never
shrinks and never stops early -- it sees all ``max_examples`` inputs and we
observe *every* crash in the run. A naive ``@given`` test that asserts "no
crash" would abort at the first one, finding at most one bug per campaign.

*Minimize* then runs once per unique crash signature, with a test that fails
only on that specific signature. That failure is what invokes the shrinker, so
the reproducer we report is genuinely minimal rather than the first crashing
input we happened to see (Step 5.4).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

from .coverage import GeneratedInput, instrumented
from .outcomes import Outcome, RunResult
from .runner import HarnessRunner
from .triage import CrashSignature, signature_for

MAX_EXAMPLES = 500
"""Per-iteration example cap from the assignment Constraints."""

MAX_WALL_CLOCK_S = 600.0
"""Ten-minute backstop from the Constraints section.

500 inputs through a small C library finish in well under a minute, so this
should never fire. It exists for the pathological case the assignment names:
a strategy emitting inputs so large that process spawning dominates. Without
it the ceiling is 500 x the 5s per-input timeout, i.e. about 42 minutes.
"""

MAX_REJECTION_SAMPLES = 25
"""Enough rejection messages to show the LLM *why* inputs are being refused,
few enough to keep the refinement prompt cheap."""

PER_INPUT_LOG_PREVIEW = 200
"""Bytes of each input kept in the per-input log. Whole inputs would bloat the
log (crash reproducers here reach 137 KB) without adding much; the digest
identifies each one exactly, and crashes are saved in full elsewhere."""

_SETTINGS = dict(
    deadline=None,  # a subprocess round-trip dwarfs Hypothesis's default deadline
    database=None,  # campaigns must be independent; no cross-run example reuse
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.large_base_example,
    ],
)


@dataclass
class CrashRecord:
    """Everything needed to triage and report one unique crash."""

    signature: CrashSignature
    first_input: bytes
    stderr: str
    hit_count: int = 1
    minimized: str | None = None


@dataclass(frozen=True)
class CampaignResult:
    """Aggregate of one campaign, and the input to the LLM refinement prompt."""

    total: int
    outcome_counts: Counter = field(default_factory=Counter)
    productions_seen: frozenset[str] = frozenset()
    depth_histogram: Counter = field(default_factory=Counter)
    crashes: dict[str, CrashRecord] = field(default_factory=dict)
    rejection_messages: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    deadline_hit: bool = False
    """True if MAX_WALL_CLOCK_S stopped the run before ``max_examples``.
    Worth surfacing rather than hiding: a truncated campaign means the
    iteration's numbers cover fewer inputs than the others."""

    @property
    def acceptance_rate(self) -> float:
        """Share of inputs the parser accepted.

        The guardrail for the whole loop. Near zero means the generator is being
        turned away at the front door and nothing past the tokenizer is under
        test; near one means it only emits well-formed documents and never
        probes error paths.
        """
        if not self.total:
            return 0.0
        return self.outcome_counts[Outcome.ACCEPT.value] / self.total

    @property
    def bug_count(self) -> int:
        return len(self.crashes)

    def summary(self) -> str:
        """Compact human- and LLM-readable digest of the run."""
        counts = ", ".join(
            f"{name}={self.outcome_counts[name]}"
            for name in sorted(self.outcome_counts)
        )
        depths = ", ".join(
            f"d{depth}:{n}" for depth, n in sorted(self.depth_histogram.items())
        )
        lines = [
            f"examples={self.total}  {counts}",
            f"acceptance_rate={self.acceptance_rate:.1%}",
            f"unique_crash_signatures={self.bug_count}",
            f"productions_exercised={sorted(self.productions_seen)}",
            f"depth_histogram={depths or 'none'}",
        ]
        if self.deadline_hit:
            lines.append(
                f"WALL CLOCK CAP HIT after {self.elapsed_s:.0f}s -- run truncated "
                "below max_examples; the strategy is generating pathologically "
                "expensive inputs"
            )
        return "\n".join(lines)


def run_campaign(
    text_strategy: st.SearchStrategy[str],
    runner: HarnessRunner,
    max_examples: int = MAX_EXAMPLES,
    max_wall_clock_s: float = MAX_WALL_CLOCK_S,
    per_input_log: Path | None = None,
) -> CampaignResult:
    """Survey pass: run the strategy through the harness, observing everything.

    ``per_input_log`` writes one JSON object per input (Step 3's per-input
    record: outcome, exit code, and either the sanitizer report or the parser's
    own rejection message). It is the raw material the aggregate summary is
    condensed from, kept on disk so a run can be audited after the fact.
    """
    outcome_counts: Counter = Counter()
    depth_histogram: Counter = Counter()
    productions: set[str] = set()
    crashes: dict[str, CrashRecord] = {}
    rejections: list[str] = []

    started = time.monotonic()
    state = {"deadline_hit": False, "index": 0}

    log_handle = None
    if per_input_log is not None:
        per_input_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = per_input_log.open("w", encoding="utf-8")

    @settings(max_examples=max_examples, phases=[Phase.generate], **_SETTINGS)
    @given(instrumented(text_strategy))
    def survey(generated: GeneratedInput) -> None:
        # Hypothesis has no whole-run wall clock, so past the cap the remaining
        # examples become no-ops rather than being run. Skipped inputs are not
        # counted, which is why `total` can come in under max_examples.
        if state["deadline_hit"] or time.monotonic() - started > max_wall_clock_s:
            state["deadline_hit"] = True
            return

        result = runner.run(generated.encode())

        outcome_counts[result.outcome.value] += 1
        depth_histogram[generated.max_depth] += 1
        productions.update(generated.productions)

        if signature := signature_for(result):
            _record_crash(crashes, signature, result)
        elif (
            result.outcome is Outcome.REJECT
            and len(rejections) < MAX_REJECTION_SAMPLES
        ):
            if message := _first_line(result.stderr):
                rejections.append(message)

        if log_handle is not None:
            log_handle.write(
                json.dumps(_per_input_record(state["index"], generated, result)) + "\n"
            )
            state["index"] += 1

    try:
        survey()
    finally:
        if log_handle is not None:
            log_handle.close()

    return CampaignResult(
        total=sum(outcome_counts.values()),
        outcome_counts=outcome_counts,
        productions_seen=frozenset(productions),
        depth_histogram=depth_histogram,
        crashes=crashes,
        rejection_messages=rejections,
        elapsed_s=time.monotonic() - started,
        deadline_hit=state["deadline_hit"],
    )


def _per_input_record(
    index: int, generated: GeneratedInput, result: RunResult
) -> dict:
    """One input's outcome, in the shape Step 3 asks to log."""
    raw = result.input_bytes
    record = {
        "i": index,
        "outcome": result.outcome.value,
        "crashed": result.outcome.is_bug,
        "exit_code": result.exit_code,
        "signal": result.signal_name,
        "ms": round(result.duration_s * 1000, 1),
        "depth": generated.max_depth,
        "bytes": len(raw),
        "sha1": hashlib.sha1(raw).hexdigest(),
        "preview": raw[:PER_INPUT_LOG_PREVIEW].decode("utf-8", errors="replace"),
    }
    # Sanitizer output when it crashed, the parser's own complaint when it
    # did not -- the two halves Step 3 distinguishes between.
    if result.outcome.is_bug:
        record["sanitizer"] = result.stderr
    else:
        record["error"] = _first_line(result.stderr)
    return record


def minimize(
    text_strategy: st.SearchStrategy[str],
    runner: HarnessRunner,
    target_signature_id: str,
    max_examples: int = MAX_EXAMPLES,
) -> str | None:
    """Shrink pass: smallest input still reproducing one specific signature.

    Works by making the test *fail* on the target signature, which is what puts
    Hypothesis's shrinker to work. Each failing call overwrites ``smallest``, so
    when shrinking converges the last write is the minimal reproducer.

    Returns ``None`` if this campaign could not re-reach the signature -- a real
    outcome worth reporting, since it means the crash is rare enough that the
    reproducer is not reliable.
    """
    smallest: str | None = None

    @settings(
        max_examples=max_examples,
        phases=[Phase.generate, Phase.shrink],
        **_SETTINGS,
    )
    @given(instrumented(text_strategy))
    def reproduce(generated: GeneratedInput) -> None:
        nonlocal smallest
        result = runner.run(generated.encode())
        signature = signature_for(result)
        if signature is not None and signature.signature_id == target_signature_id:
            smallest = generated.text
            raise AssertionError(f"reproduced {target_signature_id}")

    try:
        reproduce()
    except AssertionError:
        pass  # expected: the failure is the mechanism, not an error

    return smallest


def minimize_all(
    text_strategy: st.SearchStrategy[str],
    runner: HarnessRunner,
    result: CampaignResult,
    max_examples: int = MAX_EXAMPLES,
) -> None:
    """Fill in ``CrashRecord.minimized`` for every signature found."""
    for signature_id, record in result.crashes.items():
        record.minimized = minimize(
            text_strategy, runner, signature_id, max_examples=max_examples
        )


def _record_crash(
    crashes: dict[str, CrashRecord], signature: CrashSignature, result: RunResult
) -> None:
    if existing := crashes.get(signature.signature_id):
        existing.hit_count += 1
        return
    crashes[signature.signature_id] = CrashRecord(
        signature=signature,
        first_input=result.input_bytes,
        stderr=result.stderr,
    )


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0].strip() if text.strip() else ""
