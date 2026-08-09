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

from collections import Counter
from dataclasses import dataclass, field

from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

from .coverage import GeneratedInput, instrumented
from .outcomes import Outcome, RunResult
from .runner import HarnessRunner
from .triage import CrashSignature, signature_for

MAX_EXAMPLES = 500
"""Per-iteration example cap from the assignment Constraints."""

MAX_REJECTION_SAMPLES = 25
"""Enough rejection messages to show the LLM *why* inputs are being refused,
few enough to keep the refinement prompt cheap."""

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
        return "\n".join(
            [
                f"examples={self.total}  {counts}",
                f"acceptance_rate={self.acceptance_rate:.1%}",
                f"unique_crash_signatures={self.bug_count}",
                f"productions_exercised={sorted(self.productions_seen)}",
                f"depth_histogram={depths or 'none'}",
            ]
        )


def run_campaign(
    text_strategy: st.SearchStrategy[str],
    runner: HarnessRunner,
    max_examples: int = MAX_EXAMPLES,
) -> CampaignResult:
    """Survey pass: run the strategy through the harness, observing everything."""
    outcome_counts: Counter = Counter()
    depth_histogram: Counter = Counter()
    productions: set[str] = set()
    crashes: dict[str, CrashRecord] = {}
    rejections: list[str] = []

    @settings(max_examples=max_examples, phases=[Phase.generate], **_SETTINGS)
    @given(instrumented(text_strategy))
    def survey(generated: GeneratedInput) -> None:
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

    survey()

    return CampaignResult(
        total=sum(outcome_counts.values()),
        outcome_counts=outcome_counts,
        productions_seen=frozenset(productions),
        depth_histogram=depth_histogram,
        crashes=crashes,
        rejection_messages=rejections,
    )


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
