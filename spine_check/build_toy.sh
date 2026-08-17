#!/usr/bin/env bash
# Builds the toy target used to validate the Python spine.
#
# Same flags the real harness uses:
#   -fsanitize=address,undefined   catch memory-safety and UB
#   -fno-sanitize-recover=all      UBSan aborts instead of print-and-continue
#                                  (otherwise a UB bug prints "runtime error:"
#                                  and still exits 0, so the fuzzer scores it
#                                  clean)
#   -fno-omit-frame-pointer        keep stack traces walkable for dedup
#   -g                             symbolize frames so signatures are stable
#   -O0                            toy only, keeps the planted bugs from being
#                                  optimized away -- real target uses -O1
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${HERE}/build"

mkdir -p "${OUT}"

gcc -std=c11 -O0 -g -fno-omit-frame-pointer \
    -fsanitize=address,undefined \
    -fno-sanitize-recover=all \
    -o "${OUT}/toy_parser" \
    "${HERE}/toy_parser.c"

echo "built: ${OUT}/toy_parser"
