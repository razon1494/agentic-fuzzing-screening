# Agentic Fuzzing — parson (JSON)

Grammar-seeded, LLM-refined fuzzer built for [Prof. Marcelo D'Amorim's](https://github.com/damorim)
NC State PhD screening assignment. Full spec: [assignment_agentic_fuzzing.md](assignment_agentic_fuzzing.md).

Approach: give an LLM a formal ANTLR grammar for the target format, have it produce a
[Hypothesis](https://hypothesis.readthedocs.io/) strategy that generates strings in that grammar's
language, run the strategy through a sanitizer-instrumented C harness, and feed the results back to
the LLM for up to 5 rounds of refinement. No coverage instrumentation on the target is allowed, so the
steering signal has to come from somewhere else — see [Design decisions](#design-decisions).

## Target

[kgabis/parson](https://github.com/kgabis/parson) (JSON), pinned at `ba29f4e`. Chosen from the
assignment's list because its Constraints section reports a trial run of this exercise on
parson/JSON, which calibrates the target's difficulty to the 5-iteration budget.

## Status

| # | Deliverable | Status |
|---|---|---|
| 1 | Grammar source + adaptations | **done** — [`grammar/`](grammar/): `JSON.g4` pinned, 12 measured accept/reject gaps in [`ADAPTATIONS.md`](grammar/ADAPTATIONS.md) |
| 2 | Build script + harness | **done** — [`target/`](target/): sanitizer build verified, 19/19 samples classified correctly |
| 3 | Baseline strategy + pipeline demo | **done** — `run_baseline.py`, validated against `spine_check/` |
| 4 | Agentic loop + final generator + iteration log | spine done (`fuzzer/campaign.py`, `fuzzer/coverage.py`); LLM client/prompts not started |
| 5 | Deduplicated, minimized crash reports | machinery done (`fuzzer/triage.py`); no campaign run against parson yet |
| 6 | Two-page report | not started |

## Architecture

Bottom-up, target-independent up to the harness boundary:

```
outcomes.py    accept / reject / crash / timeout vocabulary
runner.py      executes the sanitizer-built harness on one input, classifies the result
triage.py      sanitizer report -> normalized, dedupable crash signature
coverage.py    instruments a Hypothesis strategy: which grammar productions fired, how deep
campaign.py    survey pass (sees every crash, not just the first) + shrink pass (minimal repro)
```

Everything in `fuzzer/` holds for any target that respects the exit-code contract (0 = accept, 1 =
well-formed reject, anything else = bug). Swapping the target only touches `target/harness.c` and the
grammar-derived strategy — nothing in `fuzzer/` changes.

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
  clearing the front door, production coverage says what part of the grammar is still unexercised.
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

# Steps 1-2: fetch parson at its pinned commit, build with sanitizers, verify
./target/build.sh
python3 target/test_harness.py         # expect 19/19 classified correctly
```

Still to come: `run_agentic_loop.py` runs the 5-iteration seed → run → summarize → refine loop against
the parson harness, writing each round to `logs/` and `strategies/`.

## Repo layout

```
.
├── assignment_agentic_fuzzing.md  original spec, unmodified
├── requirements.txt
├── .env.example                   ANTHROPIC_API_KEY template — copy to .env, never commit .env
│
├── grammar/                       Step 1 — done
│   ├── JSON.g4                        grammars-v4 JSON grammar, pinned at e1c222f
│   ├── SOURCE.md                      provenance: upstream commit, why this grammar/target
│   └── ADAPTATIONS.md                 measured accept/reject gaps, and what they imply for the generator
│
├── target/                        Step 2 — done
│   ├── build.sh                       fetches parson at ba29f4e, builds lib + harness with sanitizers
│   ├── harness.c                      C driver: stdin -> json_parse_string, exit-code contract
│   ├── test_harness.py                Step 2 checkpoint: 19 samples, accept vs reject
│   └── samples/{valid,invalid}/       corpus encoding parson's real accepted language
│
├── fuzzer/                        target-independent spine — done
│   ├── outcomes.py
│   ├── runner.py
│   ├── triage.py
│   ├── coverage.py
│   ├── campaign.py
│   └── agent/                         Step 4 LLM loop — not started
│       ├── prompts.py                     seed + refine prompt templates
│       ├── client.py                      Anthropic API wrapper, cost/token logging
│       └── loop.py                        5-iteration orchestration
│
├── strategies/                    generated Hypothesis strategies, one file per iteration — pending
├── spine_check/                   toy target validating the spine before the real target — done
│   ├── toy_parser.c
│   ├── build_toy.sh
│   └── test_spine.py
│
├── run_baseline.py                Step 3 — naive strategy, pipeline demonstration — done
├── run_agentic_loop.py            Step 4 entrypoint — pending
│
├── logs/                          per-iteration CampaignResult summaries — pending
├── crashes/                       Step 5 — deduplicated, minimized reproducers — pending
│   └── <signature_id>/
│       ├── input.bin
│       ├── sanitizer_report.txt
│       └── notes.md
│
└── report/
    └── report.md                  Step 6 — two-page written report — pending
```

## Constraints (from the assignment)

- 500 examples per iteration, 10-minute wall-clock cap per run
- 5 iterations or ~$5 of LLM spend, whichever comes first — log both in the report
- 5-second per-input timeout; timeouts count as crashes (a hang is a DoS bug, not a pass)

## Submission

Repo will be shared with Prof. D'Amorim's GitHub account (`damorim`) once the checklist above is
complete.
