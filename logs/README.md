# logs/

Per-iteration output from `run_agentic_loop.py` (Steps 4-5), one subdirectory per target
(`json-parson/`, `toml-tomlc99/`), one markdown file per round: rationale, changes from the previous
iteration, and the measured `CampaignResult.summary()` (outcome counts, acceptance rate, productions
exercised, depth histogram, crash signatures found so far). This is the "log of how it evolved across
iterations" deliverable and the source data for each target's written report.
