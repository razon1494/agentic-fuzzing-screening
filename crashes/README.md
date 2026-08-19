# crashes/

Step 5 deliverable, one subdirectory per target (`json-parson/`, `toml-tomlc99/`). Within each, one
subdirectory per unique crash signature (`fuzzer/triage.CrashSignature.signature_id`):

```
crashes/<target-slug>/<signature_id>/
├── input.bin                 the reproducer as submitted (git-attributes marks crashes/** binary).
│                             Minimized when the shrinker could re-reach the crash, otherwise the
│                             first input that hit it -- notes.md says which
├── sanitizer_report.txt      stderr from the first input that hit this signature during the survey
├── verification_stderr.txt   stderr from re-running input.bin itself, plus its exit/signal
└── notes.md                  bug class, hit count, which iteration first hit it, and the standalone
                              re-run's verdict
```

Two reports rather than one because they can come from two different inputs: the survey input that
first hit the signature, and the possibly-shrunk one saved as `input.bin`. Filing only the first
against the second would misattribute the evidence.

If a target's campaign found no crashes, its subdirectory instead gets a single `NONE_FOUND.md`
explaining why, per the assignment's fallback requirement — see `json-parson/NONE_FOUND.md`.
