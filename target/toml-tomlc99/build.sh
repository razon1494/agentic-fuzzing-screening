#!/usr/bin/env bash
# Fetches tomlc99 at its pinned commit and builds it with the fuzzing harness.
#
# Structurally identical to target/json-parson/build.sh -- see that file for
# the full rationale on each sanitizer flag. The library is fetched, never
# vendored: targets/ is gitignored, so a clone of this repo reproduces the
# exact build from the pin below.
set -euo pipefail

# Pinned per the assignment: "Do not build against the latest upstream version."
TOMLC99_REPO="https://github.com/cktan/tomlc99.git"
TOMLC99_COMMIT="29076dfd095bbbbd50a3c1b2760d29f4b83e74ac"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
SRC="${REPO_ROOT}/targets/tomlc99"
OUT="${HERE}/build"

fetch_target() {
    if [[ ! -d "${SRC}/.git" ]]; then
        echo "cloning tomlc99 -> targets/tomlc99"
        rm -rf "${SRC}"
        git clone --quiet "${TOMLC99_REPO}" "${SRC}"
    fi

    git -C "${SRC}" checkout --quiet "${TOMLC99_COMMIT}"

    local actual
    actual="$(git -C "${SRC}" rev-parse HEAD)"
    if [[ "${actual}" != "${TOMLC99_COMMIT}" ]]; then
        echo "FATAL: targets/tomlc99 is at ${actual}, expected ${TOMLC99_COMMIT}" >&2
        exit 1
    fi
    echo "target pinned at ${TOMLC99_COMMIT}"
}

build_harness() {
    mkdir -p "${OUT}"
    gcc -std=c99 -O1 -g -fno-omit-frame-pointer \
        -fsanitize=address,undefined \
        -fno-sanitize-recover=all \
        -I"${SRC}" \
        -o "${OUT}/tomlc99_harness" \
        "${HERE}/harness.c" "${SRC}/toml.c"
    echo "built: ${OUT}/tomlc99_harness"
}

fetch_target
build_harness
