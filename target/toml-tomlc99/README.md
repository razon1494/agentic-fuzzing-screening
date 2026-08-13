# target/toml-tomlc99/

Step 2 deliverable — done. Target: [tomlc99](https://github.com/cktan/tomlc99) at pinned commit
`29076dfd095bbbbd50a3c1b2760d29f4b83e74ac`.

- [`build.sh`](build.sh) — same fetch/pin-verify/sanitizer-build shape as `target/json-parson/build.sh`.
- [`harness.c`](harness.c) — reads stdin, calls `toml_parse`, exits per the same contract as the JSON
  harness: 0 accept, 1 well-formed reject, 2 harness error, anything else a bug.
- [`test_harness.py`](test_harness.py) — the checkpoint. 18 samples, all classified correctly.
- `samples/` — split by tomlc99's *measured* behavior; see
  [`../../grammar/toml-tomlc99/ADAPTATIONS.md`](../../grammar/toml-tomlc99/ADAPTATIONS.md) for the full
  gap analysis, including a real stack-overflow bug found here during Step 1/2 probing (deeply nested
  arrays or inline tables — no depth cap in the library).

## Verify

```bash
./target/toml-tomlc99/build.sh && python3 target/toml-tomlc99/test_harness.py
```
