# Agentic Fuzzing — parson (JSON) + tomlc99 (TOML)

Grammar-seeded, LLM-refined fuzzer built for [Prof. Marcelo D'Amorim's](https://github.com/damorim)
NC State PhD screening assignment. Full spec: [assignment_agentic_fuzzing.md](assignment_agentic_fuzzing.md).

Approach: give an LLM a formal ANTLR grammar for the target format, have it produce a
[Hypothesis](https://hypothesis.readthedocs.io/) strategy that generates strings in that grammar's
language, run the strategy through a sanitizer-instrumented C harness, and feed the results back to
the LLM for up to 5 rounds of refinement. No coverage instrumentation on the target is allowed, so the
steering signal has to come from somewhere else — see [Design decisions](#design-decisions).

## Targets

The assignment asks for one target. This repo has two:

| Target | Library | Grammar | Status |
|---|---|---|---|
| **json-parson** | [kgabis/parson](https://github.com/kgabis/parson) @ `ba29f4e` | grammars-v4 `json/JSON.g4` | Original submission — 0 crashes in 2,500 inputs |
| **toml-tomlc99** | [cktan/tomlc99](https://github.com/cktan/tomlc99) @ `29076df` | grammars-v4 `toml/{TomlParser,TomlLexer}.g4` | Added second — found a real stack-overflow bug |

`json-parson` was chosen first because the assignment's own Constraints section reports a trial run of
this exercise on parson/JSON, calibrating its difficulty to the 5-iteration budget. It found no
crashes. Rather than stop there, `toml-tomlc99` was added to answer two questions at once: is the
`fuzzer/` spine genuinely target-independent, and does a richer, less-hardened target behave
differently? Both answers turned out to be yes — nothing in `fuzzer/outcomes.py`, `runner.py`,
`triage.py`, `coverage.py`, or `campaign.py` changed to support the second target, and TOML's Step 1
probing surfaced a real stack-overflow bug (unbounded recursion in nested arrays/inline tables — no
depth cap in tomlc99, unlike parson's explicit `MAX_NESTING 2048`) before the agentic loop even ran.
See [`grammar/toml-tomlc99/ADAPTATIONS.md`](grammar/toml-tomlc99/ADAPTATIONS.md) for the full writeup.

## Status

Deliverables 1–6, per target:

| # | Deliverable | json-parson | toml-tomlc99 |
|---|---|---|---|
| 1 | Grammar source + adaptations | **done** — [`grammar/json-parson/`](grammar/json-parson/) | **done** — [`grammar/toml-tomlc99/`](grammar/toml-tomlc99/), includes the stack-overflow finding |
| 2 | Build script + harness | **done** — [`target/json-parson/`](target/json-parson/), 19/19 samples | **done** — [`target/toml-tomlc99/`](target/toml-tomlc99/), 18/18 samples |
| 3 | Baseline strategy + pipeline demo | **done** — `run_baseline.py` (target-independent, validated against `spine_check/`) ||
| 4 | Agentic loop + final generator + iteration log | **done** — [`strategies/json-parson/`](strategies/json-parson/) + [`logs/json-parson/`](logs/json-parson/) | **done** — [`strategies/toml-tomlc99/`](strategies/toml-tomlc99/) + [`logs/toml-tomlc99/`](logs/toml-tomlc99/) |
| 5 | Deduplicated, minimized crash reports | **done** — none found, [`crashes/json-parson/NONE_FOUND.md`](crashes/json-parson/NONE_FOUND.md) | **done** — 4 signatures / 1 confirmed bug, [`crashes/toml-tomlc99/`](crashes/toml-tomlc99/) |
| 6 | Two-page report | **done** — [`report/report.md`](report/report.md) | **done** — [`report/report-toml-tomlc99.md`](report/report-toml-tomlc99.md) (bonus, supplementary) |

**json-parson run:** 5 iterations, 2,500 inputs, 0 crashes, $0.8584 of the $5.00 budget. Depth moved
8 → 2052 across the run (iteration 2 diagnosed its own instrumentation bug from the depth histogram
alone) and acceptance held at 40–59%. Full analysis: [`report/report.md`](report/report.md).

**toml-tomlc99 run:** 5 iterations, 2,500 inputs, **4 crash signatures / 1 confirmed root cause**
(`AddressSanitizer: stack-overflow` — unbounded recursion in tomlc99's array and inline-table parsing,
no depth cap), $2.76 of the $5.00 budget. All four reproducers re-verified standalone. Full analysis,
including why 4 signatures collapse to 1 real bug: [`report/report-toml-tomlc99.md`](report/report-toml-tomlc99.md).

## Architecture

Bottom-up, target-independent up to the harness boundary:

```
outcomes.py    accept / reject / crash / timeout vocabulary
runner.py      executes the sanitizer-built harness on one input, classifies the result
triage.py      sanitizer report -> normalized, dedupable crash signature
coverage.py    instruments a Hypothesis strategy: which grammar productions fired, how deep
campaign.py    survey pass (sees every crash, not just the first) + shrink pass (minimal repro)
agent/         LLM loop: prompts, Anthropic client, seed -> validate -> run -> summarize -> refine
```

**Nothing above changed to add the second target.** `fuzzer/agent/targets.py` is the one file that
knows what's different between `json-parson` and `toml-tomlc99` — grammar files, library name, entry
point, expected productions — and `prompts.py`/`loop.py` are parameterized by it rather than hardcoded.
Swapping or adding a target means one new `TargetConfig`, one grammar directory, and one harness;
`fuzzer/` itself is untouched.

## Design decisions

- **Crash vs. rejection.** A parser saying "invalid input" is correct behavior; a sanitizer abort or
  fatal signal is a bug. `ASAN_OPTIONS=abort_on_error=1` is mandatory — ASan's default exit code (1)
  collides with our reject code, so without it every memory bug would be silently filed as a clean
  rejection. See `fuzzer/runner.py`.
- **Proxy signal.** The assignment bans instrumenting the *target*, not the *generator*. Each
  `@st.composite` strategy declares which grammar production it's currently expanding
  (`fuzzer/coverage.py`), giving two free, fully-blackbox signals: which productions have fired, and how
  deep recursion actually went. Paired with acceptance rate (parser-accepted / total), that's the full
  steering signal fed back to the LLM each iteration — acceptance rate says whether the generator is
  clearing the front door, production coverage says what part of the grammar is still unexercised. This
  signal is exactly what found the TOML stack-overflow's *shape*: depth is the one thing the signal
  measures that a coverage tool doesn't need to.
- **Dedup.** Top-3 symbolized stack frames, sanitizer runtime frames and libc stripped, addresses/line
  numbers/bare integers normalized out before hashing. See `fuzzer/triage.py` for the full rationale
  behind each normalization choice and its failure mode.
- **Survey and minimize are separate Hypothesis passes.** A single `@given` test asserting "no crash"
  stops at the first failure — at most one bug per campaign. `campaign.run_campaign` runs
  `Phase.generate` only so nothing stops early; `campaign.minimize` then runs once per unique signature
  with a targeted assertion so the shrinker actually engages. See `fuzzer/campaign.py`.

## Quickstart

Requires Linux/WSL (sanitizer builds don't work natively on Windows) and Python 3.12+.

```bash
python3 -m venv ~/.venvs/fuzz && source ~/.venvs/fuzz/bin/activate
pip install -r requirements.txt

# Validate the spine against a deliberately buggy toy parser
./spine_check/build_toy.sh
python3 spine_check/test_spine.py      # expect 6/6 pass

# Step 3: baseline strategy + full pipeline demonstration
python3 run_baseline.py

# Steps 1-2, either target: fetch, build with sanitizers, verify
./target/json-parson/build.sh  && python3 target/json-parson/test_harness.py   # 19/19
./target/toml-tomlc99/build.sh && python3 target/toml-tomlc99/test_harness.py  # 18/18
```

```bash
# Steps 4-5: the agentic loop, then crash triage. Needs ANTHROPIC_API_KEY
# (export it, or copy .env.example to .env). Spends real money — up to $5 per target.
python3 run_agentic_loop.py --target json-parson
python3 run_agentic_loop.py --target toml-tomlc99
```

Each iteration writes its strategy to `strategies/<target>/iteration_N.py` and its rationale, changes,
and measured results to `logs/<target>/iteration_N.md`. The winning iteration is copied to
`strategies/<target>/final.py`, and every unique crash gets a verified `crashes/<target>/<signature_id>/`
directory.

## Repo layout

```
.
├── assignment_agentic_fuzzing.md  original spec, unmodified
├── requirements.txt
├── .env.example                   ANTHROPIC_API_KEY template — copy to .env, never commit .env
│
├── grammar/
│   ├── json-parson/                   JSON.g4, SOURCE.md, ADAPTATIONS.md (12 measured gaps)
│   └── toml-tomlc99/                  TomlParser.g4, TomlLexer.g4, SOURCE.md, ADAPTATIONS.md
│                                       (measured gaps + the stack-overflow finding)
│
├── target/
│   ├── json-parson/                   build.sh, harness.c, test_harness.py, samples/ — 19/19
│   └── toml-tomlc99/                  build.sh, harness.c, test_harness.py, samples/ — 18/18
│
├── fuzzer/                        target-independent spine
│   ├── outcomes.py
│   ├── runner.py
│   ├── triage.py
│   ├── coverage.py
│   ├── campaign.py
│   └── agent/
│       ├── targets.py                 the ONE file that differs per target
│       ├── prompts.py                 grammar + measured gaps in, strategy contract out
│       ├── client.py                  Anthropic call, budget enforcement, cost ledger
│       └── loop.py                    seed → validate → run → summarize → refine
│
├── strategies/
│   ├── json-parson/                   iteration_0..4.py, final.py
│   └── toml-tomlc99/                  iteration_0..N.py, final.py
│
├── spine_check/                   toy target validating the spine before any real target
│   ├── toy_parser.c
│   ├── build_toy.sh
│   └── test_spine.py
│
├── run_baseline.py                Step 3 — naive strategy, pipeline demonstration
├── run_agentic_loop.py            Steps 4-5 entrypoint — takes --target
│
├── logs/
│   ├── json-parson/                   iteration_0..4.md
│   └── toml-tomlc99/                  iteration_0..N.md
│
├── crashes/
│   ├── json-parson/                   NONE_FOUND.md
│   └── toml-tomlc99/                  <signature_id>/{input.bin, sanitizer_report.txt, notes.md}
│
└── report/
    ├── report.md                      Step 6 — primary two-page report (json-parson)
    └── report-toml-tomlc99.md         bonus supplementary report (toml-tomlc99)
```

## Constraints (from the assignment)

- 500 examples per iteration, 10-minute wall-clock cap per run
- 5 iterations or ~$5 of LLM spend, whichever comes first — log both in the report
- 5-second per-input timeout; timeouts count as crashes (a hang is a DoS bug, not a pass)

Each target's loop is budgeted and logged independently — running both costs at most ~$10 combined,
not shared.

## Submission

Repo will be shared with Prof. D'Amorim's GitHub account (`damorim`) once the checklist above is
complete.
