# DEADLYSIGNAL

- signature: `28379cb26912`
- frames: malloc@asan_malloc_linux.cpp <- expand@toml.c <- expand_arritem@toml.c
- hits during the run: 1
- minimized: NO -- crash too rare to re-reach; first-seen input kept instead
- reproducer size: 62770 bytes
- found by: strategies/toml-tomlc99/iteration_2.py

## Standalone verification

Re-ran `input.bin` against the pinned build: **crash** (crash          SIGABRT      72.6ms).

Reproduces deterministically.
