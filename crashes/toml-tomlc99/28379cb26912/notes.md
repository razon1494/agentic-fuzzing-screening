# DEADLYSIGNAL

- signature: `28379cb26912`
- frames: malloc@asan_malloc_linux.cpp <- expand@toml.c <- expand_arritem@toml.c
- hits across the run (all iterations): 6
- minimized: NO -- crash too rare to re-reach; first-seen input kept instead
- reproducer size: 62770 bytes
- first found by: strategies/toml-tomlc99/iteration_1.py

## Standalone verification

Re-ran `input.bin` against the pinned build: **crash** (crash          SIGABRT      72.6ms).

Reproduces deterministically.

`sanitizer_report.txt` is the survey-pass report for the first input that hit this signature; `verification_stderr.txt` is the report for `input.bin` as submitted.
