#!/usr/bin/env bash
# Fetches parson at its pinned commit and builds it with the fuzzing harness.
#
# Fetched into targets/ (gitignored), never vendored, so a fresh clone always
# builds from the exact pin below.
#
# Flags:
#   -fsanitize=address,undefined   catch memory-safety and UB
#   -fno-sanitize-recover=all      UBSan aborts instead of print-and-continue
#                                  (otherwise a bug prints "runtime error:"
#                                  and still exits 0, so it scores as clean)
#   -fno-omit-frame-pointer        keep stack traces walkable for triage.py
#   -g                             symbolize frames, or dedup blurs
#   -O1                            ASan's recommended level -- representative
#                                  without inlining away the stack trace
#                                  (spine_check/ uses -O0 since its bugs are
#                                  planted and -O1 would optimize them away)
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

    # Every crash we report only means something against this exact commit --
    # catch a stale or hand-edited checkout before it silently changes that.
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
