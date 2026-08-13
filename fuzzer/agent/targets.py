"""Per-target configuration: what makes json-parson and toml-tomlc99 different.

Everything in fuzzer/ above this file -- outcomes, runner, triage, coverage,
campaign, and the agentic loop itself -- is target-independent by construction.
This module is the one place that says which grammar, which library, and which
directories a run uses. Adding a third target means adding one more TargetConfig
here; nothing else in the loop changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class GrammarFile:
    """One grammar file to paste into the prompt, with its citation."""

    label: str
    """How the file is introduced in the prompt, e.g. 'json/JSON.g4'."""
    path: Path


@dataclass(frozen=True)
class TargetConfig:
    """Everything the agentic loop needs to know about one fuzzing target."""

    slug: str
    """Directory name used under grammar/, target/, strategies/, logs/, crashes/."""

    format_name: str
    """What the generator produces, e.g. "JSON", "TOML" -- used in prompt prose."""

    grammar_files: tuple[GrammarFile, ...]
    grammar_commit: str
    """Short commit hash of antlr/grammars-v4, for the prompt's citation line."""

    adaptations_path: Path
    """grammar/<slug>/ADAPTATIONS.md -- measured grammar-vs-reality gaps."""

    library_name: str
    """e.g. "parson (kgabis/parson)" -- used in prompt prose."""

    library_commit: str
    """Short commit hash of the pinned target library."""

    entry_point: str
    """The C function the harness calls, e.g. "json_parse_string"."""

    strategy_entry_name: str
    """The Python callable the generated module must define, e.g. "json_document"."""

    expected_productions: frozenset[str]
    """Grammar rule names the generator is asked to instrument. Anything in here
    that never shows up in a run's productions_seen is a real, reportable gap."""

    harness_binary: str
    """Filename of the built harness, e.g. "parson_harness"."""

    @property
    def grammar_dir(self) -> Path:
        return REPO_ROOT / "grammar" / self.slug

    @property
    def target_dir(self) -> Path:
        return REPO_ROOT / "target" / self.slug

    @property
    def harness_path(self) -> Path:
        return self.target_dir / "build" / self.harness_binary

    @property
    def strategies_dir(self) -> Path:
        return REPO_ROOT / "strategies" / self.slug

    @property
    def logs_dir(self) -> Path:
        return REPO_ROOT / "logs" / self.slug

    @property
    def crashes_dir(self) -> Path:
        return REPO_ROOT / "crashes" / self.slug


JSON_PARSON = TargetConfig(
    slug="json-parson",
    format_name="JSON",
    grammar_files=(
        GrammarFile(label="json/JSON.g4", path=REPO_ROOT / "grammar" / "json-parson" / "JSON.g4"),
    ),
    grammar_commit="e1c222f",
    adaptations_path=REPO_ROOT / "grammar" / "json-parson" / "ADAPTATIONS.md",
    library_name="parson (kgabis/parson)",
    library_commit="ba29f4e",
    entry_point="json_parse_string",
    strategy_entry_name="json_document",
    expected_productions=frozenset(
        {
            # Parser rules from JSON.g4, plus the three keyword literals `value`
            # can expand to.
            "value",
            "obj",
            "pair",
            "arr",
            "STRING",
            "NUMBER",
            "true",
            "false",
            "null",
        }
    ),
    harness_binary="parson_harness",
)

TOML_TOMLC99 = TargetConfig(
    slug="toml-tomlc99",
    format_name="TOML",
    grammar_files=(
        GrammarFile(
            label="toml/TomlParser.g4",
            path=REPO_ROOT / "grammar" / "toml-tomlc99" / "TomlParser.g4",
        ),
        GrammarFile(
            label="toml/TomlLexer.g4",
            path=REPO_ROOT / "grammar" / "toml-tomlc99" / "TomlLexer.g4",
        ),
    ),
    grammar_commit="e1c222f",
    adaptations_path=REPO_ROOT / "grammar" / "toml-tomlc99" / "ADAPTATIONS.md",
    library_name="tomlc99 (cktan/tomlc99)",
    library_commit="29076df",
    entry_point="toml_parse",
    strategy_entry_name="toml_document",
    expected_productions=frozenset(
        {
            # A practical subset of TomlParser.g4's rules -- the ones with real
            # structural or semantic weight. Pure formatting rules (comment_or_nl,
            # nl_or_comment, expression) are left out: instrumenting them would
            # only measure whitespace placement, not grammar coverage.
            "key_value",
            "dotted_key",
            "table",
            "array_table",
            "inline_table",
            "array_",
            "string",
            "integer",
            "floating_point",
            "bool_",
            "date_time",
        }
    ),
    harness_binary="tomlc99_harness",
)

REGISTRY: dict[str, TargetConfig] = {
    JSON_PARSON.slug: JSON_PARSON,
    TOML_TOMLC99.slug: TOML_TOMLC99,
}


def get_target(slug: str) -> TargetConfig:
    try:
        return REGISTRY[slug]
    except KeyError:
        available = ", ".join(sorted(REGISTRY))
        raise ValueError(f"unknown target {slug!r}; available: {available}") from None
