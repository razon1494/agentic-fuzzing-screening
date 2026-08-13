# crashes/

Step 5 deliverable, one subdirectory per target (`json-parson/`, `toml-tomlc99/`). Within each, one
subdirectory per unique crash signature (`fuzzer/triage.CrashSignature.signature_id`):

```
crashes/<target-slug>/<signature_id>/
├── input.bin              exact minimized reproducer bytes (git-attributes marks crashes/** binary)
├── sanitizer_report.txt   full stderr from the crashing run
└── notes.md               bug class, hit count, verification that the standalone re-run reproduces it
```

If a target's campaign found no crashes, its subdirectory instead gets a single `NONE_FOUND.md`
explaining why, per the assignment's fallback requirement — see `json-parson/NONE_FOUND.md`.
