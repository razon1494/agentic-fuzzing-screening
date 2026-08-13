# crashes/

Step 5 deliverable. One subdirectory per unique crash signature (`fuzzer/triage.CrashSignature.signature_id`):

```
crashes/<signature_id>/
├── input.bin              exact minimized reproducer bytes (git-attributes marks crashes/** binary)
├── sanitizer_report.txt   full stderr from the crashing run
└── notes.md               bug class, hit count, verification that the standalone re-run reproduces it
```

If no crashes are found against the assigned target, this directory instead gets a single
`NONE_FOUND.md` explaining why, per the assignment's fallback requirement.
