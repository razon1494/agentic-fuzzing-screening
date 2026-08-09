/* A deliberately buggy stand-in for the real target library.
 *
 * This exists only to prove the Python spine (runner + triage) correctly
 * distinguishes accept / reject / crash / timeout BEFORE the assigned library
 * is known. It parses a toy S-expression language:
 *
 *     expr   := list | number | atom
 *     list   := '(' expr* ')'
 *     number := [0-9]+
 *     atom   := [a-zA-Z]+
 *
 * Three bugs are planted on purpose, one per failure mode we need to observe.
 * Delete this whole directory once the real harness works.
 */

#include <ctype.h>
#include <stdio.h>

#define MAX_INPUT 65536

static const char *cursor;

static int parse_expr(void);

/* PLANTED BUG A: fixed buffer, no bound check -> stack-buffer-overflow (ASan).
 * Triggered by any atom longer than 15 characters. */
static int parse_atom(void) {
    char token[16];
    int n = 0;

    while (isalpha((unsigned char)*cursor)) {
        token[n++] = *cursor++;
    }
    token[n] = '\0';

    /* Consume the token so the optimizer cannot delete the array outright. */
    int checksum = 0;
    for (int i = 0; i < n; i++) {
        checksum += token[i];
    }
    return (n > 0 && checksum >= 0) ? 0 : -1;
}

/* PLANTED BUG B: unchecked accumulation -> signed-integer-overflow (UBSan).
 * Triggered by any integer literal above INT_MAX. */
static int parse_number(void) {
    int value = 0;

    if (!isdigit((unsigned char)*cursor)) {
        return -1;
    }
    while (isdigit((unsigned char)*cursor)) {
        value = value * 10 + (*cursor++ - '0');
    }
    return value >= 0 ? 0 : 0;
}

/* PLANTED BUG C: `continue` without advancing the cursor -> infinite loop.
 * Triggered by a '~' inside a list. This is the hang case, which the
 * assignment says to treat as a crash. */
static int parse_list(void) {
    cursor++; /* consume '(' */

    while (*cursor != '\0' && *cursor != ')') {
        if (*cursor == '~') {
            continue;
        }
        if (parse_expr() != 0) {
            return -1;
        }
    }

    if (*cursor != ')') {
        return -1;
    }
    cursor++;
    return 0;
}

static int parse_expr(void) {
    while (*cursor == ' ') {
        cursor++;
    }
    if (*cursor == '(') {
        return parse_list();
    }
    if (isdigit((unsigned char)*cursor)) {
        return parse_number();
    }
    if (isalpha((unsigned char)*cursor)) {
        return parse_atom();
    }
    return -1;
}

int main(void) {
    static char buffer[MAX_INPUT];

    size_t length = fread(buffer, 1, sizeof(buffer) - 1, stdin);
    buffer[length] = '\0';
    cursor = buffer;

    /* Exit contract, mirrored in fuzzer/outcomes.py:
     *   0 -> valid parse
     *   1 -> well-formed rejection (NOT a bug)
     *   anything else -> sanitizer abort or fatal signal (a bug) */
    return parse_expr() == 0 ? 0 : 1;
}
