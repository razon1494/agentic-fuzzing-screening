/* Fuzzing harness for parson (JSON), pinned commit ba29f4e.
 *
 * Reads one input from stdin, hands it to the library's parse entry point, and
 * exits with a code the Python side can classify. The exit contract is mirrored
 * in fuzzer/outcomes.py and must not drift from it:
 *
 *     0  accept          json_parse_string returned a value
 *     1  reject          json_parse_string returned NULL -- a well-formed
 *                        "this is not valid JSON". NOT a bug.
 *     2  harness error   the harness itself failed (allocation). Not the
 *                        library's fault; surfaces as HARNESS_ERROR so a broken
 *                        harness can never masquerade as a clean parse.
 *
 * Anything else -- a fatal signal or a sanitizer abort -- is a bug in parson,
 * which is the entire point of the exercise.
 */

#include <stdio.h>
#include <stdlib.h>

#include "parson.h"

#define EXIT_ACCEPT        0
#define EXIT_REJECT        1
#define EXIT_HARNESS_ERROR 2

/* Cap on how much stdin we read. A generator that has gone pathological can
 * emit inputs large enough that process spawning and I/O dominate the run,
 * which the assignment's 10-minute wall-clock backstop exists to catch. Bound
 * it here too so one bad iteration degrades throughput instead of wedging the
 * campaign. Inputs beyond the cap are truncated, not rejected. */
#define MAX_INPUT (1u << 20) /* 1 MiB */
#define INITIAL_CAPACITY 65536u

/* Slurp stdin into a NUL-terminated heap buffer. Returns NULL on allocation
 * failure. Caller frees.
 *
 * Note the format's boundary here: json_parse_string takes a C string, so an
 * embedded NUL byte truncates the input from parson's point of view. That is a
 * real property of the library's API, not a harness limitation, and it is
 * documented as such in grammar/ADAPTATIONS.md. */
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
                break; /* truncate: the cap is deliberate, see above */
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
            break; /* EOF or read error; either way we have all we are getting */
        }
    }

    /* Room for the terminator. Only reallocates in the exact-fit case. */
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

    JSON_Value *parsed = json_parse_string(input);

    /* Freed before the tree is touched, on purpose. parson's API hands back an
     * owning tree, so nothing it returns may point into our buffer. If some
     * path does retain a pointer, ASan reports a use-after-free here and that
     * is a genuine lifetime bug in the library, not a harness artifact.
     *
     * If a crash ever traces back to this line and turns out to be intended
     * behaviour, the conservative fallback is to move this free() below
     * json_value_free() -- but that would stop testing the lifetime contract,
     * so it is not the default. */
    free(input);

    if (parsed == NULL) {
        return EXIT_REJECT;
    }

    json_value_free(parsed);
    return EXIT_ACCEPT;
}
