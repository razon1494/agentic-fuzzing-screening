# DEADLYSIGNAL

- signature: `dad118d628ee`
- frames: strnlen@sanitizer_common_interceptors.inc <- STRNDUP@toml.c <- normalize_key@toml.c
- hits during the run: 1
- minimized: NO -- crash too rare to re-reach; first-seen input kept instead
- reproducer size: 117933 bytes
- first found by: strategies/toml-tomlc99/iteration_1.py

## Standalone verification

Re-ran `input.bin` against the pinned build: **crash** (crash          SIGABRT     125.7ms).

Reproduces deterministically.

`sanitizer_report.txt` is the survey-pass report for the first input that hit this signature; `verification_stderr.txt` is the report for `input.bin` as submitted.
