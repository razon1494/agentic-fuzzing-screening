/* Fuzzing harness for tomlc99 (TOML), pinned commit 29076df.
 *
 * Reads one input from stdin, hands it to the library's parse entry point, and
 * exits with a code the Python side can classify. Mirrors the contract in
 * target/json-parson/harness.c and fuzzer/outcomes.py:
 *
 *     0  accept          toml_parse returned a non-NULL table
 *     1  reject          toml_parse returned NULL -- a well-formed
 *                        "this is not valid TOML". NOT a bug.
 *     2  harness error   the harness itself failed (allocation).
 *
 * Anything else -- a fatal signal or a sanitizer abort -- is a bug in tomlc99.
 */

#include <stdio.h>
#include <stdlib.h>

#include "toml.h"

#define EXIT_ACCEPT        0
#define EXIT_REJECT        1
#define EXIT_HARNESS_ERROR 2

/* Same rationale as the parson harness: bound pathological-input runtime. */
#define MAX_INPUT (1u << 20) /* 1 MiB */
#define INITIAL_CAPACITY 65536u

#define ERRBUF_SIZE 256

/* Slurp stdin into a NUL-terminated heap buffer. Returns NULL on allocation
 * failure. Caller frees.
 *
 * toml_parse's signature takes `char *conf` (not const), and its doc comment
 * says "NUL terminated, please" -- same contract as parson's json_parse_string,
 * so this buffer-reading logic is deliberately identical to that harness's. */
static char *read_all_stdin(void) {
    size_t capacity = INITIAL_CAPACITY;
    size_t length = 0;
    char *buffer = malloc(capacity);

    if (buffer == NULL) {
        return NULL;
    }

    for (;;) {
        if (length == capacity) {
            if (capacity >= MAX_INPUT) {
                break;
            }

            size_t grown = capacity * 2;
            if (grown > MAX_INPUT) {
                grown = MAX_INPUT;
            }

            char *resized = realloc(buffer, grown);
            if (resized == NULL) {
                free(buffer);
                return NULL;
            }
            buffer = resized;
            capacity = grown;
        }

        size_t got = fread(buffer + length, 1, capacity - length, stdin);
        length += got;
        if (got == 0) {
            break;
        }
    }

    if (length == capacity) {
        char *resized = realloc(buffer, capacity + 1);
        if (resized == NULL) {
            free(buffer);
            return NULL;
        }
        buffer = resized;
    }

    buffer[length] = '\0';
    return buffer;
}

int main(void) {
    char *input = read_all_stdin();
    if (input == NULL) {
        fprintf(stderr, "harness: could not allocate input buffer\n");
        return EXIT_HARNESS_ERROR;
    }

    char errbuf[ERRBUF_SIZE];
    toml_table_t *parsed = toml_parse(input, errbuf, sizeof(errbuf));

    /* Same deliberate ordering as the parson harness: free the input buffer
     * before the parse tree. toml_parse's own doc comment says the returned
     * table must be freed via toml_free() and gives no indication it retains
     * pointers into the input, so if it does, ASan reports the resulting
     * use-after-free as the real lifetime bug it would be. */
    free(input);

    if (parsed == NULL) {
        return EXIT_REJECT;
    }

    toml_free(parsed);
    return EXIT_ACCEPT;
}
