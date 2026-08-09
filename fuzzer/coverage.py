"""Production coverage: the proxy signal that steers the agentic loop.

The assignment forbids coverage instrumentation of the target, which removes the
signal a normal fuzzer optimizes against. The move made here is that the ban
applies to the *target* -- nothing stops us instrumenting the *generator*.

Each strategy declares the grammar production it is currently expanding::

    @st.composite
    def json_object(draw):
        with production("object"):
            ...

That yields two things per generated input, for free and fully blackbox:

  * which productions of the grammar the input actually exercises, so the loop
    can tell the LLM "you have never once produced a nested array", and
  * how deep the recursion went, so a generator that claims to be recursive but
    flattens in practice is caught immediately.

Paired with the parser's own acceptance rate (from :mod:`fuzzer.campaign`) this
is the full steering signal: production coverage says *what to reach for*,
acceptance rate says *whether the reaching is producing anything the parser will
look at*.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass

from hypothesis import strategies as st


@dataclass(frozen=True)
class GeneratedInput:
    """One generated input plus the structural facts about how it was built."""

    text: str
    productions: frozenset[str]
    max_depth: int

    def encode(self) -> bytes:
        """Bytes to feed the harness.

        ``surrogatepass`` keeps lone surrogates intact instead of raising. Those
        are exactly the inputs worth sending to a C parser that assumes
        well-formed UTF-8, so refusing to encode them would discard some of the
        most interesting cases the grammar can express.
        """
        return self.text.encode("utf-8", errors="surrogatepass")


class _Recorder:
    """Accumulates productions and depth for the example being built.

    Deliberately a single module-level instance rather than a ContextVar.
    Hypothesis draws one example at a time on one thread, and ``instrumented``
    resets immediately before drawing, so the window is unambiguous. If this
    ever runs under Hypothesis's parallel execution the design must change to a
    ContextVar -- noted here because the failure would be silent, showing up as
    productions bleeding between examples rather than as an error.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._depth = 0
        self._max_depth = 0

    def reset(self) -> None:
        self._seen = set()
        self._depth = 0
        self._max_depth = 0

    def mark(self, name: str) -> None:
        self._seen.add(name)

    @contextlib.contextmanager
    def scope(self, name: str) -> Iterator[None]:
        self.mark(name)
        self._depth += 1
        self._max_depth = max(self._max_depth, self._depth)
        try:
            yield
        finally:
            self._depth -= 1

    def snapshot(self) -> tuple[frozenset[str], int]:
        return frozenset(self._seen), self._max_depth


_RECORDER = _Recorder()


def record_production(name: str) -> None:
    """Note that a terminal production fired. Use for leaves: numbers, strings."""
    _RECORDER.mark(name)


def production(name: str) -> contextlib.AbstractContextManager[None]:
    """Note a production and track nesting depth. Use for recursive rules.

    Wrap the body of any ``@st.composite`` that can contain itself::

        with production("array"):
            items = draw(st.lists(value_strategy))
    """
    return _RECORDER.scope(name)


@st.composite
def instrumented(draw, inner: st.SearchStrategy[str]) -> GeneratedInput:
    """Wrap a text strategy so each example carries its coverage facts.

    Reset-then-draw is what bounds the recording window to a single example.
    """
    _RECORDER.reset()
    text = draw(inner)
    productions, max_depth = _RECORDER.snapshot()
    return GeneratedInput(text=text, productions=productions, max_depth=max_depth)
