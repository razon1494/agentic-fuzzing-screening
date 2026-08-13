"""Hypothesis strategy for generating JSON-like documents to fuzz parson.

This module follows the ANTLR JSON.g4 grammar for its core structure (value,
obj, arr, pair, STRING, NUMBER, true/false/null) while also sprinkling in a
modest amount of edge-case material (empty containers, malformed numbers,
unicode escapes, lone surrogates, duplicate keys, trailing commas, trailing
garbage, a UTF-8 BOM, an embedded NUL, and deep nesting near parson's
measured recursion wall). The bulk of generated documents remain valid,
grammar-conformant JSON so the parser is exercised on the middle of the
format, not just its edges.
"""

from hypothesis import strategies as st

from fuzzer.coverage import production, record_production

HEXDIGITS = "0123456789abcdefABCDEF"


@st.composite
def json_string(draw):
    """STRING : '"' (ESC | SAFECODEPOINT)* '"' -- plus deliberate edge cases."""
    record_production("STRING")
    mode = draw(st.integers(min_value=0, max_value=99))

    if mode < 70:
        # Ordinary safe codepoints (SAFECODEPOINT), no quotes/backslashes/control chars.
        content = draw(
            st.text(
                alphabet=st.characters(
                    min_codepoint=0x20,
                    max_codepoint=0x10FFFF,
                    exclude_characters='"\\',
                    exclude_categories=("Cs",),
                ),
                max_size=16,
            )
        )
        return '"' + content + '"'
    elif mode < 85:
        # Explicit ESC sequences, including a well-formed \uXXXX escape.
        simple_escapes = ['\\"', "\\\\", "\\/", "\\b", "\\f", "\\n", "\\r", "\\t"]
        pieces = draw(st.lists(st.sampled_from(simple_escapes), max_size=5))
        if draw(st.booleans()):
            digits = "".join(draw(st.sampled_from(list(HEXDIGITS))) for _ in range(4))
            pieces.append("\\u" + digits)
        return '"' + "".join(pieces) + '"'
    elif mode < 92:
        # Lone surrogate escape sequence: grammar allows it, parson rejects it.
        surrogate = draw(st.sampled_from(["d800", "dbff", "dc00", "dfff", "d9ab"]))
        return '"\\u' + surrogate + '"'
    else:
        # Raw high-byte content, represented via surrogate-escape codepoints so
        # a downstream byte-oriented encode() can turn this back into the exact
        # invalid UTF-8 bytes parson sees at the byte level.
        n = draw(st.integers(min_value=1, max_value=6))
        raw_bytes = [draw(st.integers(min_value=0x80, max_value=0xFF)) for _ in range(n)]
        chars = [chr(0xDC00 + b) for b in raw_bytes]
        return '"' + "".join(chars) + '"'


@st.composite
def json_number(draw):
    """NUMBER : '-'? INT ('.' [0-9]+)? EXP? -- plus deliberate malformed variants."""
    record_production("NUMBER")
    mode = draw(st.integers(min_value=0, max_value=99))

    if mode < 70:
        sign = "-" if draw(st.booleans()) else ""
        if draw(st.booleans()):
            intpart = "0"
        else:
            intpart = str(draw(st.integers(min_value=1, max_value=999999999)))
        frac = ""
        if draw(st.booleans()):
            digits = "".join(str(d) for d in draw(st.lists(st.integers(0, 9), min_size=1, max_size=6)))
            frac = "." + digits
        exp = ""
        if draw(st.booleans()):
            e = draw(st.sampled_from(["e", "E"]))
            esign = draw(st.sampled_from(["", "+", "-"]))
            edigits = "".join(str(d) for d in draw(st.lists(st.integers(0, 9), min_size=1, max_size=3)))
            exp = e + esign + edigits
        return sign + intpart + frac + exp
    elif mode < 80:
        # Trailing dot with no fractional digits: grammar rejects, parson accepts.
        sign = "-" if draw(st.booleans()) else ""
        intpart = str(draw(st.integers(min_value=0, max_value=999)))
        return sign + intpart + "."
    elif mode < 88:
        # Huge exponent: grammar allows, parson overflow-rejects.
        sign = "-" if draw(st.booleans()) else ""
        base = str(draw(st.integers(min_value=1, max_value=9)))
        exponent = str(draw(st.integers(min_value=500, max_value=9999)))
        return sign + base + "e" + exponent
    elif mode < 94:
        # Leading zero: both grammar and parson reject this.
        digits = "".join(str(d) for d in draw(st.lists(st.integers(0, 9), min_size=1, max_size=4)))
        return "0" + digits
    else:
        # Leading plus sign: both reject.
        return "+" + str(draw(st.integers(min_value=0, max_value=999)))


@st.composite
def json_true(draw):
    record_production("true")
    return "true"


@st.composite
def json_false(draw):
    record_production("false")
    return "false"


@st.composite
def json_null(draw):
    record_production("null")
    return "null"


def json_bool():
    return st.one_of(json_true(), json_false())


def _base_value():
    return st.one_of(json_string(), json_number(), json_bool(), json_null())


@st.composite
def _json_object(draw, children):
    """obj : '{' pair (',' pair)* '}' | '{' '}' -- plus trailing comma / dup keys."""
    with production("obj"):
        n = draw(st.integers(min_value=0, max_value=6))
        if n == 0:
            return "{}"
        pairs = []
        last_key = None
        for _ in range(n):
            record_production("pair")
            reuse_key = last_key is not None and draw(st.integers(min_value=0, max_value=99)) < 4
            key = last_key if reuse_key else draw(json_string())
            value = draw(children)
            pairs.append(key + ":" + value)
            last_key = key
        body = ",".join(pairs)
        if draw(st.integers(min_value=0, max_value=99)) < 6:
            body += ","  # single trailing comma: parson tolerates it
        return "{" + body + "}"


@st.composite
def _json_array(draw, children):
    """arr : '[' value (',' value)* ']' | '[' ']' -- plus trailing comma."""
    with production("arr"):
        n = draw(st.integers(min_value=0, max_value=6))
        if n == 0:
            return "[]"
        items = [draw(children) for _ in range(n)]
        body = ",".join(items)
        if draw(st.integers(min_value=0, max_value=99)) < 6:
            body += ","  # single trailing comma: parson tolerates it
        return "[" + body + "]"


def _extend_value(children):
    return st.one_of(_json_object(children), _json_array(children))


# Slightly larger max_leaves than before to push more mass into deeper
# recursive structures (previous run: depth histogram concentrated at 3-5,
# max depth only 8).
_value_strategy = st.recursive(_base_value(), _extend_value, max_leaves=90)


@st.composite
def json_value(draw):
    """value : STRING | NUMBER | obj | arr | 'true' | 'false' | 'null'."""
    with production("value"):
        return draw(_value_strategy)


@st.composite
def _deep_nesting(draw):
    """Explicit deep nesting straddling parson's measured MAX_NESTING wall.

    Arrays accept depth 2049 and reject 2050; objects accept 2048 and reject
    2049. We sample a range that covers both sides of the wall for either
    shape without special-casing which exact boundary applies. This is
    layered on top of the 'arr'/'obj' productions rather than substituting
    for them, so the coverage counters below still record real traversal.
    """
    shape = draw(st.sampled_from(["array", "object"]))
    depth = draw(st.integers(min_value=2000, max_value=2055))
    if shape == "array":
        with production("arr"):
            return "[" * depth + "1" + "]" * depth
    else:
        with production("obj"):
            return ("{\"a\":" * depth) + "1" + ("}" * depth)


@st.composite
def json_document(draw):
    """json : value EOF -- plus superset edge cases parson actually accepts.

    Note: the top-level 'json' rule itself is not one of the recognized
    production names tracked by the coverage harness (only the grammar's
    internal rules -- obj, pair, arr, value, STRING, NUMBER, true, false,
    null -- are), so it is intentionally left uninstrumented here rather
    than recorded under an unrecognized name.
    """
    roll = draw(st.integers(min_value=0, max_value=99))

    if roll < 4:
        # Explicit deep-nesting probe near the measured recursion wall.
        return draw(_deep_nesting())

    val = draw(json_value())

    if roll < 9:
        # UTF-8 BOM prefix: no grammar production for this, parson accepts it.
        val = "\ufeff" + val
    elif roll < 14:
        # Trailing garbage after the first parsed value: parson stops early.
        val = val + " trailing garbage"
    elif roll < 17:
        # Looks like a comment but is really just tolerated trailing garbage.
        val = val + " // hi"
    elif roll < 19:
        # Embedded NUL: the C string API truncates here.
        val = val + "\x00garbage-after-nul"

    return val
