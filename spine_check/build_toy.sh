#!/usr/bin/env bash
# Builds the toy target used to validate the Python spine.
#
# The flags here are the ones that will carry over to the real harness:
#
#   -fsanitize=address,undefined   catch memory-safety and UB
#   -fno-sanitize-recover=all      make UBSan ABORT rather than print-and-continue.
#                                  Without this a pure UB bug prints "runtime
#                                  error:" and still exits 0, and the fuzzer
#                                  scores it as a clean parse.
#   -fno-omit-frame-pointer        keep stack traces walkable for dedup
#   -g                             symbolize frames so signatures are stable
#   -O0                            toy only: keeps the planted bugs from being
#                                  optimized away. The real target uses -O1,
#                                  which is what ASan documentation recommends.
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
