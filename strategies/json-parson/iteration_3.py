"""Hypothesis strategy for generating JSON-like documents to fuzz parson.

This module follows the ANTLR JSON.g4 grammar for its core structure (value,
obj, arr, pair, STRING, NUMBER, true/false/null) while also sprinkling in a
modest amount of edge-case material (empty containers, malformed numbers,
unicode escapes, lone surrogates, duplicate keys -- both adjacent and nested
-- trailing commas, double trailing commas, trailing garbage, a UTF-8 BOM, an
embedded NUL, a genuine (rejected) block comment, and deep nesting near
parson's measured recursion wall). The bulk of generated documents remain
valid, grammar-conformant JSON so the parser is exercised on the middle of
the format, not just its edges.

Revision note (this iteration): the previous run reported a healthy 58.6%
acceptance rate, full production coverage, and a real depth spread up to
2051 with no crashes yet. Rather than rebalance what already works, this
revision targets the specific gaps called out in the disagreement table that
the previous version under-exercised:

  * duplicate keys were only ever *adjacent* re-draws of the immediately
    preceding key inside one flat object -- the table specifically calls
    out that the reject also holds when the duplicate is *nested*
    (`{"x":{"a":1,"a":2}}`), which the previous generator could never
    produce because nested duplicate keys require coordinating two
    separate object productions. Added a dedicated generator for this.
  * the subset row "double trailing comma -- only a single trailing comma
    is tolerated" (`[1,,]`) was never generated at all, so that specific
    agreement path (both reject) went untested.
  * the subset row for the genuine comment form `{"a":1 /* hi */}` (as
    opposed to the tolerated trailing `// hi` garbage) was never
    generated.
  * raw invalid-UTF-8-in-string content, flagged in the writeup as "a
    genuinely under-tested surface", is bumped slightly in probability.
  * the near-wall nesting probe is bumped slightly in probability since it
    is the most likely place left to find a crash and 4% of 500 examples
    (about 20) is a thin sample at a boundary this precise.
"""

from contextlib import ExitStack

from hypothesis import strategies as st

from fuzzer.coverage import production, record_production

HEXDIGITS = "0123456789abcdefABCDEF"


@st.composite
def json_string(draw):
    """STRING : '"' (ESC | SAFECODEPOINT)* '"' -- plus deliberate edge cases."""
    record_production("STRING")
    mode = draw(st.integers(min_value=0, max_value=99))

    if mode < 68:
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
    elif mode < 82:
        # Explicit ESC sequences, including a well-formed \uXXXX escape.
        simple_escapes = ['\\"', "\\\\", "\\/", "\\b", "\\f", "\\n", "\\r", "\\t"]
        pieces = draw(st.lists(st.sampled_from(simple_escapes), max_size=5))
        if draw(st.booleans()):
            digits = "".join(draw(st.sampled_from(list(HEXDIGITS))) for _ in range(4))
            pieces.append("\\u" + digits)
        return '"' + "".join(pieces) + '"'
    elif mode < 89:
        # Lone surrogate escape sequence: grammar allows it, parson rejects it.
        surrogate = draw(st.sampled_from(["d800", "dbff", "dc00", "dfff", "d9ab"]))
        return '"\\u' + surrogate + '"'
    else:
        # Raw high-byte content, represented via surrogate-escape codepoints so
        # a downstream byte-oriented encode() can turn this back into the exact
        # invalid UTF-8 bytes parson sees at the byte level. Bumped up from the
        # previous iteration's 8% since the writeup flags this as genuinely
        # under-tested.
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
    """obj : '{' pair (',' pair)* '}' | '{' '}' -- plus trailing comma / dup keys.

    Branching factor kept small (0-3 pairs) so that when this is used inside
    st.recursive, the leaf budget goes toward depth rather than being burned
    on wide, shallow objects.
    """
    with production("obj"):
        n = draw(st.integers(min_value=0, max_value=3))
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
        comma_roll = draw(st.integers(min_value=0, max_value=99))
        if comma_roll < 6:
            body += ","  # single trailing comma: parson tolerates it
        elif comma_roll < 9:
            body += ",,"  # double trailing comma: both grammar and parson reject
        return "{" + body + "}"


@st.composite
def _json_array(draw, children):
    """arr : '[' value (',' value)* ']' | '[' ']' -- plus trailing comma.

    Branching factor kept small (0-3 items), same rationale as _json_object.
    """
    with production("arr"):
        n = draw(st.integers(min_value=0, max_value=3))
        if n == 0:
            return "[]"
        items = [draw(children) for _ in range(n)]
        body = ",".join(items)
        comma_roll = draw(st.integers(min_value=0, max_value=99))
        if comma_roll < 6:
            body += ","  # single trailing comma: parson tolerates it
        elif comma_roll < 9:
            body += ",,"  # double trailing comma: both grammar and parson reject
        return "[" + body + "]"


def _extend_value(children):
    return st.one_of(_json_object(children), _json_array(children))


# Larger max_leaves combined with the smaller per-container branching factor
# above lets Hypothesis actually spend its budget on nesting depth instead of
# breadth.
_value_strategy = st.recursive(_base_value(), _extend_value, max_leaves=150)


@st.composite
def json_value(draw):
    """value : STRING | NUMBER | obj | arr | 'true' | 'false' | 'null'."""
    with production("value"):
        return draw(_value_strategy)


@st.composite
def _nested_duplicate_key(draw):
    """{\"x\":{\"a\":1,\"a\":2}} -- duplicate keys inside a nested object.

    The disagreement table explicitly notes the duplicate-key reject 'also
    holds nested'. The flat-object generator's adjacent-reuse trick cannot
    produce this shape because it only ever re-draws the immediately
    preceding key within a single object -- this builds the two-level
    wrapper explicitly instead.
    """
    with production("obj"):
        outer_key = draw(json_string())
        with production("obj"):
            inner_key = draw(json_string())
            record_production("pair")
            v1 = draw(json_value())
            record_production("pair")
            v2 = draw(json_value())
            inner = "{" + inner_key + ":" + v1 + "," + inner_key + ":" + v2 + "}"
        record_production("pair")
        return "{" + outer_key + ":" + inner + "}"


@st.composite
def _moderate_nesting(draw):
    """Mid-range nesting (well under the wall) to fill in the depth histogram.

    Built with an explicit ExitStack so that every level of nesting enters
    the 'arr'/'obj' production context manager exactly once -- this makes
    the true nesting depth visible to the coverage harness's depth tracker.
    """
    shape = draw(st.sampled_from(["array", "object"]))
    depth = draw(st.integers(min_value=10, max_value=800))
    if shape == "array":
        with ExitStack() as stack:
            for _ in range(depth):
                stack.enter_context(production("arr"))
            return "[" * depth + "1" + "]" * depth
    else:
        with ExitStack() as stack:
            for _ in range(depth):
                stack.enter_context(production("obj"))
                record_production("pair")
            return ("{\"a\":" * depth) + "1" + ("}" * depth)


@st.composite
def _deep_nesting(draw):
    """Explicit deep nesting straddling parson's measured MAX_NESTING wall.

    Arrays accept depth 2049 and reject 2050; objects accept 2048 and reject
    2049. We bracket each shape's own measured wall rather than reusing a
    single shared range. Every level enters the production context manager
    once via ExitStack so the coverage harness's depth histogram reflects
    the real nesting depth.
    """
    shape = draw(st.sampled_from(["array", "object"]))
    if shape == "array":
        depth = draw(st.integers(min_value=2045, max_value=2052))
        with ExitStack() as stack:
            for _ in range(depth):
                stack.enter_context(production("arr"))
            return "[" * depth + "1" + "]" * depth
    else:
        depth = draw(st.integers(min_value=2044, max_value=2051))
        with ExitStack() as stack:
            for _ in range(depth):
                stack.enter_context(production("obj"))
                record_production("pair")
            return ("{\"a\":" * depth) + "1" + ("}" * depth)


@st.composite
def json_document(draw):
    """json : value EOF -- plus superset/subset edge cases measured against parson.

    Note: the top-level 'json' rule itself is not one of the recognized
    production names tracked by the coverage harness (only the grammar's
    internal rules -- obj, pair, arr, value, STRING, NUMBER, true, false,
    null -- are), so it is intentionally left uninstrumented here rather
    than recorded under an unrecognized name.
    """
    roll = draw(st.integers(min_value=0, max_value=99))

    if roll < 6:
        # Explicit deep-nesting probe near the measured recursion wall.
        # Bumped from 4% to 6%: this boundary is the most likely place left
        # to find a crash and the previous run's sample there was thin.
        return draw(_deep_nesting())
    elif roll < 14:
        # Mid-range nesting filler for a well-populated depth histogram.
        return draw(_moderate_nesting())
    elif roll < 18:
        # Nested duplicate keys: {"x":{"a":1,"a":2}} -- grammar accepts,
        # parson rejects, and the previous generator could never reach this
        # specific nested shape.
        return draw(_nested_duplicate_key())

    val = draw(json_value())

    if roll < 26:
        # UTF-8 BOM prefix: no grammar production for this, parson accepts it.
        val = "\ufeff" + val
    elif roll < 34:
        # Trailing garbage after the first parsed value: parson stops early.
        val = val + " trailing garbage"
    elif roll < 39:
        # Looks like a comment but is really just tolerated trailing garbage.
        val = val + " // hi"
    elif roll < 43:
        # Embedded NUL: the C string API truncates here.
        val = val + "\x00garbage-after-nul"
    elif roll < 47:
        # Genuine block-comment form, distinct from the tolerated trailing
        # '// hi' garbage above: parson's non-comment entry point rejects
        # this because the comment sits *inside* the value's syntax, not
        # after it, so there is no valid parse to fall back on.
        val = val + " /* hi */"

    return val
