"""Turns a sanitizer report into a stable crash signature for deduplication.

Deduplication is what decides whether you found *one* bug or *five*, so the
normalization choices here are a graded deliverable. Each one is spelled out
below with its rationale and its failure mode.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .outcomes import Outcome, RunResult

TOP_FRAMES = 3
"""How many stack frames make up a signature.

Too few and genuinely distinct bugs that share a common victim function collapse
together. Too many and one bug reached via two call paths looks like two bugs.
Three is the usual fuzzing-triage default and it is what the spec's "top few
frames" suggests.
"""

_ASAN_ERROR = re.compile(r"(?:AddressSanitizer|LeakSanitizer):\s*([a-zA-Z0-9_-]+)")
_UBSAN_ERROR = re.compile(r"runtime error:\s*(.+)")

# Both shapes a sanitizer frame can take:
#   "    #0 0x5591... in parse_atom /src/toy_parser.c:42:9"
#   "    #3 0x7f3d...  (/lib/x86_64-linux-gnu/libc.so.6+0x2a1c9) (BuildId: ...)"
# The function name is optional; the location is whatever follows. The location
# is matched with `.+?` rather than `\S+` on purpose -- build paths routinely
# contain spaces (e.g. a Windows/OneDrive checkout mounted under WSL), and a
# `\S+` here silently matches nothing, yielding empty frame lists and collapsing
# every distinct bug of the same class into a single signature.
_FRAME = re.compile(
    r"^\s*#\d+\s+0x[0-9a-f]+\s+(?:in\s+(?P<func>\S+)\s+)?(?P<loc>.+?)\s*$"
)
# "(/lib/x86_64-linux-gnu/libc.so.6+0x2a1c9)" -> the library it lives in
_LIBRARY_OFFSET = re.compile(r"\((?P<lib>[^()]+?)\+0x[0-9a-f]+\)")
_TRAILING_LINE_COLUMN = re.compile(r"(?::\d+)+$")

_NOISE_FRAME_PREFIXES = (
    "__asan",
    "__ubsan",
    "__sanitizer",
    "__interceptor",
    "__lsan",
)
"""Sanitizer runtime frames sit on top of every report and carry no information
about which bug fired, so they are dropped before the top-N window is taken."""

_RUNTIME_LIBRARIES = ("libc.so", "libasan.so", "libubsan.so", "ld-linux")
"""Unsymbolized frames inside these are dropped for the same reason: every
report ends in libc's __libc_start_main, which would make all signatures rhyme."""

_VOLATILE_TOKENS = re.compile(
    r"""
      0x[0-9a-fA-F]+          # addresses
    | \b\d+\b                 # ANY bare integer, not just large ones
    | '[^']*'                 # quoted type names and values from UBSan
    """,
    re.VERBOSE,
)
"""Input-dependent noise stripped from a UBSan message before hashing.

Every bare integer goes, not merely large ones. UBSan reports out-of-bounds
access as "index 16 out of bounds for type 'char [16]'", and that index varies
with the input that triggered it -- keeping it splits one bug across many
signatures and makes the crash count meaningless. The cost is that two bugs
distinguishable *only* by a constant would now merge; no such pair has been
observed, and merging is the safer error here since a merged pair is caught on
manual inspection of the reproducer while a split bug inflates the headline
number silently.
"""


@dataclass(frozen=True)
class CrashSignature:
    """A normalized identity for one root cause."""

    signature_id: str
    bug_class: str
    frames: tuple[str, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        where = " <- ".join(self.frames) if self.frames else "<no symbolized frames>"
        return f"[{self.signature_id}] {self.bug_class}: {where}"


def signature_for(result: RunResult) -> CrashSignature | None:
    """Build a dedup signature, or ``None`` if the run was not a bug."""
    if not result.outcome.is_bug:
        return None

    if result.outcome is Outcome.TIMEOUT:
        # A hang produces no stack, so every timeout collapses to one bucket.
        # This under-counts if the target has two independent infinite loops;
        # accepted deliberately, since separating them needs a stack sample we
        # do not collect. Revisit by attaching gdb on timeout if hangs dominate.
        return CrashSignature(
            signature_id=_hash("timeout"),
            bug_class="timeout",
            frames=(),
        )

    bug_class = _extract_bug_class(result)
    frames = _extract_frames(result.stderr)
    payload = "|".join((bug_class, *frames))
    return CrashSignature(
        signature_id=_hash(payload),
        bug_class=bug_class,
        frames=frames,
    )


def _extract_bug_class(result: RunResult) -> str:
    """Name the kind of bug: 'heap-buffer-overflow', 'signed-integer-overflow'."""
    if match := _ASAN_ERROR.search(result.stderr):
        return match.group(1)

    if match := _UBSAN_ERROR.search(result.stderr):
        # UBSan messages embed the offending type and value, which vary per
        # input for the same bug. Strip them so one bug yields one signature.
        stripped = _VOLATILE_TOKENS.sub("", match.group(1))
        return " ".join(stripped.split()).strip(" :")

    # Died by signal with no sanitizer report -- e.g. a stack overflow that
    # blew past the guard page before ASan could speak.
    return f"signal-{result.signal_name or 'unknown'}"


def _extract_frames(stderr: str) -> tuple[str, ...]:
    """Top N informative frames, addresses and line numbers stripped."""
    frames: list[str] = []

    for line in stderr.splitlines():
        match = _FRAME.match(line)
        if match is None:
            continue

        function = match.group("func")
        if function and function.startswith(_NOISE_FRAME_PREFIXES):
            continue

        location = _normalize_location(match.group("loc"))
        if any(runtime in location for runtime in _RUNTIME_LIBRARIES):
            continue

        frames.append(f"{function or '??'}@{location}")
        if len(frames) >= TOP_FRAMES:
            break

    return tuple(frames)


def _normalize_location(location: str) -> str:
    """Reduce a frame's location to a stable basename.

    Absolute build paths differ between a WSL checkout and the Docker image, and
    line numbers move whenever the file is edited. Neither should change a bug's
    identity, so both are discarded and only the basename survives.
    """
    if match := _LIBRARY_OFFSET.search(location):
        return match.group("lib").rsplit("/", 1)[-1]
    return _TRAILING_LINE_COLUMN.sub("", location).rsplit("/", 1)[-1]


def _hash(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
