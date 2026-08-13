#!/usr/bin/env bash
# Fetches parson at its pinned commit and builds it with the fuzzing harness.
#
# The library is fetched, never vendored: targets/ is gitignored, so a clone of
# this repo reproduces the exact build from the pin below rather than trusting a
# copy that may have drifted.
#
# Sanitizer flags, and why each one is load-bearing:
#
#   -fsanitize=address,undefined   the whole point: catch memory-safety and UB
#                                  that a normal build silently tolerates.
#   -fno-sanitize-recover=all      make UBSan ABORT instead of print-and-continue.
#                                  Without it a pure UB bug prints "runtime
#                                  error:" and still exits 0, and the fuzzer
#                                  scores a real bug as a clean parse.
#   -fno-omit-frame-pointer        keep stack traces walkable, so triage.py can
#                                  take a stable top-3-frame signature.
#   -g                             symbolize frames; without it every signature
#                                  degrades to a library+offset and dedup blurs.
#   -O1                            what the ASan docs recommend: enough
#                                  optimization to be representative, not so
#                                  much that inlining destroys the stack trace.
#                                  (spine_check/ uses -O0 because its bugs are
#                                  planted and -O1 would optimize them away.)
set -euo pipefail

# Pinned per the assignment: "Do not build against the latest upstream version."
PARSON_REPO="https://github.com/kgabis/parson.git"
PARSON_COMMIT="ba29f4eda9ea7703a9f6a9cf2b0532a2605723c3"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
SRC="${REPO_ROOT}/targets/parson"
OUT="${HERE}/build"

fetch_target() {
    if [[ ! -d "${SRC}/.git" ]]; then
        echo "cloning parson -> targets/parson"
        rm -rf "${SRC}"
        git clone --quiet "${PARSON_REPO}" "${SRC}"
    fi

    git -C "${SRC}" checkout --quiet "${PARSON_COMMIT}"

    # Guard against a stale or hand-edited checkout silently changing what is
    # under test. Every crash we report is only meaningful against this commit.
    local actual
    actual="$(git -C "${SRC}" rev-parse HEAD)"
    if [[ "${actual}" != "${PARSON_COMMIT}" ]]; then
        echo "FATAL: targets/parson is at ${actual}, expected ${PARSON_COMMIT}" >&2
        exit 1
    fi
    echo "target pinned at ${PARSON_COMMIT}"
}

build_harness() {
    mkdir -p "${OUT}"
    gcc -std=c99 -O1 -g -fno-omit-frame-pointer \
        -fsanitize=address,undefined \
        -fno-sanitize-recover=all \
        -I"${SRC}" \
        -o "${OUT}/parson_harness" \
        "${HERE}/harness.c" "${SRC}/parson.c"
    echo "built: ${OUT}/parson_harness"
}

fetch_target
build_harness
