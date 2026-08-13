# target/json-parson/

Step 2 deliverable — done. Target: [parson](https://github.com/kgabis/parson) at pinned commit
`ba29f4eda9ea7703a9f6a9cf2b0532a2605723c3`.

- [`build.sh`](build.sh) — clones parson into gitignored `targets/` (fetched, never vendored), verifies
  the checkout really is at the pinned commit, and compiles it with `harness.c` under
  `-fsanitize=address,undefined -fno-sanitize-recover=all`. Each flag's rationale is in the header
  comment.
- [`harness.c`](harness.c) — reads stdin, calls `json_parse_string`, exits per the contract in
  `fuzzer/outcomes.py`: 0 accept, 1 well-formed reject, 2 harness error, anything else a bug.
- [`test_harness.py`](test_harness.py) — the checkpoint. 19 samples, all classified correctly.
- `samples/valid/` — inputs parson accepts, including four `ext_*` files that the formal grammar
  rejects but parson takes anyway. `samples/invalid/` — inputs it rejects cleanly. The split encodes
  parson's *measured* language, not the spec's; see [`../../grammar/json-parson/ADAPTATIONS.md`](../../grammar/json-parson/ADAPTATIONS.md).

## Verify

```bash
./target/json-parson/build.sh && python3 target/json-parson/test_harness.py
```
