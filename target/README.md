# target/

Step 2 deliverable. Blocked on the target library assignment.

Once assigned:

- `build.sh` — clones the library at its pinned commit (never latest upstream) into `targets/`
  (gitignored — fetched, not vendored) and compiles library + `harness.c` with
  `-fsanitize=address,undefined -fno-sanitize-recover=all`, mirroring `spine_check/build_toy.sh`.
- `harness.c` — C driver: reads stdin, calls the library's parse entrypoint, follows the exit-code
  contract in `fuzzer/outcomes.py` (0 = accept, 1 = well-formed reject, anything else = bug).
- `samples/` — a handful of valid and invalid inputs used to demonstrate the harness behaves correctly
  before the fuzzing loop runs (Step 2's "before moving on" checkpoint).
