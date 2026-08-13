# target/

Step 2 deliverable, per target. One subdirectory per fuzzing target:

- [`json-parson/`](json-parson/) — parson build, harness, samples. Original submission.
- [`toml-tomlc99/`](toml-tomlc99/) — tomlc99 build, harness, samples. Second target.

Both follow the same shape: `build.sh` fetches the pinned commit into gitignored `../targets/` and
compiles it with the harness under `-fsanitize=address,undefined -fno-sanitize-recover=all`;
`harness.c` implements the shared exit-code contract from `fuzzer/outcomes.py` (0 accept, 1 well-formed
reject, 2 harness error, anything else a bug); `test_harness.py` is the Step 2 checkpoint against
`samples/`.

```bash
./target/json-parson/build.sh  && python3 target/json-parson/test_harness.py
./target/toml-tomlc99/build.sh && python3 target/toml-tomlc99/test_harness.py
```
