# logs/

Per-iteration output from `run_agentic_loop.py`, one subdirectory per target, one markdown file per
round: rationale, changes from the previous iteration, and the measured `CampaignResult.summary()`.
This is the "log of how it evolved" deliverable and the source data for each target's report.

The loop also writes `iteration_N_inputs.jsonl` beside each round, holding Step 3's per-input record:
one JSON object per input with its outcome, exit code, signal, and either the sanitizer report (when
it crashed) or the parser's own rejection message (when it did not). That logging was added after
both runs had already completed, so only the markdown summaries are committed here; re-running
either target produces both.
