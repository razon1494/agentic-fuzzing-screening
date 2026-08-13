# DEADLYSIGNAL

- signature: `cfd4b257f124`
- frames: DlsymAlloc::UseImpl()@asan_malloc_linux.cpp <- malloc@asan_malloc_linux.cpp <- expand@toml.c
- hits during the run: 1
- minimized: NO -- crash too rare to re-reach; first-seen input kept instead
- reproducer size: 53941 bytes
- found by: strategies/toml-tomlc99/iteration_2.py

## Standalone verification

Re-ran `input.bin` against the pinned build: **crash** (crash          SIGABRT      71.0ms).

Reproduces deterministically.
