# DEADLYSIGNAL

- signature: `6c7a182a0eab`
- frames: <none symbolized>
- hits across the run (all iterations): 1
- minimized: yes
- reproducer size: 136867 bytes
- first found by: strategies/toml-tomlc99/iteration_2.py

## Standalone verification

Re-ran `input.bin` against the pinned build: **crash** (crash          SIGABRT     119.6ms).

Reproduces deterministically.

`sanitizer_report.txt` is the survey-pass report for the first input that hit this signature; `verification_stderr.txt` is the report for `input.bin` as submitted.
