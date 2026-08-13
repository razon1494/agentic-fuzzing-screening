import string
from contextlib import ExitStack

from hypothesis import strategies as st
from fuzzer.coverage import production, record_production


# ---------------------------------------------------------------------------
# Character helpers
# ---------------------------------------------------------------------------

UNQUOTED_KEY_CHARS = string.ascii_letters + string.digits + "-_"

SAFE_BASIC_CHARS = [c for c in map(chr, range(0x20, 0x7F)) if c not in ('"', '\\')]
SAFE_LITERAL_CHARS = [c for c in map(chr, range(0x20, 0x7F)) if c != "'"]
BASIC_ESCAPES = ['\\n', '\\t', '\\r', '\\"', '\\\\', '\\b', '\\f', '\\/']
CONTROL_BYTES = ['\x01', '\x02', '\x1f', '\x7f', '\x00']


@st.composite
def _basic_string_content(draw, multiline=False):
    n = draw(st.integers(min_value=0, max_value=12))
    parts = []
    for _ in range(n):
        choice = draw(st.integers(min_value=0, max_value=9))
        if choice < 6:
            parts.append(draw(st.sampled_from(SAFE_BASIC_CHARS)))
        elif choice < 8:
            parts.append(draw(st.sampled_from(BASIC_ESCAPES)))
        elif choice == 8:
            hexdigits = draw(st.text(alphabet="0123456789abcdefABCDEF", min_size=4, max_size=4))
            parts.append('\\u' + hexdigits)
        else:
            if multiline:
                parts.append(draw(st.sampled_from(['\n', ' \n', '\r\n'])))
            else:
                parts.append(draw(st.sampled_from(SAFE_BASIC_CHARS)))
    return "".join(parts)


@st.composite
def _literal_string_content(draw, multiline=False):
    alphabet = list(SAFE_LITERAL_CHARS)
    if multiline:
        alphabet = alphabet + ['\n']
    return draw(st.text(alphabet=alphabet, min_size=0, max_size=15))


# ---------------------------------------------------------------------------
# Terminal value productions
# ---------------------------------------------------------------------------

@st.composite
def string_value(draw):
    kind = draw(st.sampled_from([
        "basic", "basic_ml", "literal", "literal_ml", "basic_control_byte",
    ]))
    if kind == "basic":
        content = draw(_basic_string_content(multiline=False))
        record_production("string")
        return '"' + content + '"'
    elif kind == "basic_ml":
        content = draw(_basic_string_content(multiline=True))
        record_production("string")
        return '"""' + content + '"""'
    elif kind == "literal":
        content = draw(_literal_string_content(multiline=False))
        record_production("string")
        return "'" + content + "'"
    elif kind == "literal_ml":
        content = draw(_literal_string_content(multiline=True))
        record_production("string")
        return "'''" + content + "'''"
    else:
        # edge case: raw control byte inside a basic string.
        # Grammar forbids this; tomlc99 is known to accept it.
        ctrl = draw(st.sampled_from(CONTROL_BYTES))
        record_production("string")
        return '"' + ctrl + '"'


@st.composite
def integer_value(draw):
    kind = draw(st.sampled_from(["dec", "hex", "oct", "bin", "leading_zero"]))
    if kind == "dec":
        sign = draw(st.sampled_from(["", "+", "-"]))
        digits = draw(st.integers(min_value=0, max_value=10 ** 9))
        s = str(digits)
        if len(s) > 3 and draw(st.booleans()):
            mid = len(s) // 2
            s = s[:mid] + "_" + s[mid:]
        record_production("integer")
        return sign + s
    elif kind == "hex":
        digs = draw(st.text(alphabet="0123456789abcdefABCDEF", min_size=1, max_size=8))
        record_production("integer")
        return "0x" + digs
    elif kind == "oct":
        digs = draw(st.text(alphabet="01234567", min_size=1, max_size=8))
        record_production("integer")
        return "0o" + digs
    elif kind == "bin":
        digs = draw(st.text(alphabet="01", min_size=1, max_size=16))
        record_production("integer")
        return "0b" + digs
    else:
        # edge case: leading zero decimal, e.g. "01".
        # Grammar forbids; tomlc99 is known to accept it.
        digs = draw(st.text(alphabet="0123456789", min_size=2, max_size=4))
        record_production("integer")
        return "0" + digs


@st.composite
def float_value(draw):
    kind = draw(st.sampled_from(["frac", "exp", "fracexp", "inf", "nan", "dotless"]))
    if kind == "inf":
        sign = draw(st.sampled_from(["", "+", "-"]))
        record_production("floating_point")
        return sign + "inf"
    elif kind == "nan":
        sign = draw(st.sampled_from(["", "+", "-"]))
        record_production("floating_point")
        return sign + "nan"
    elif kind == "dotless":
        # edge case: ".5" with no integer part before the dot.
        # Grammar forbids; tomlc99 is known to accept it.
        digs = draw(st.text(alphabet="0123456789", min_size=1, max_size=4))
        record_production("floating_point")
        return "." + digs
    else:
        sign = draw(st.sampled_from(["", "+", "-"]))
        intpart = draw(st.integers(min_value=0, max_value=9999))
        s = sign + str(intpart)
        if kind in ("frac", "fracexp"):
            frac = draw(st.text(alphabet="0123456789", min_size=1, max_size=5))
            s += "." + frac
        if kind in ("exp", "fracexp"):
            esign = draw(st.sampled_from(["", "+", "-"]))
            edig = draw(st.integers(min_value=0, max_value=99))
            eletter = draw(st.sampled_from(["e", "E"]))
            s += eletter + esign + str(edig)
        record_production("floating_point")
        return s


@st.composite
def bool_value(draw):
    record_production("bool_")
    return draw(st.sampled_from(["true", "false"]))


@st.composite
def date_time_value(draw):
    kind = draw(st.sampled_from(["offset", "local_dt", "local_date", "local_time"]))
    year = draw(st.integers(min_value=0, max_value=9999))
    month = draw(st.integers(min_value=1, max_value=12))
    day = draw(st.integers(min_value=1, max_value=28))
    hour = draw(st.integers(min_value=0, max_value=23))
    minute = draw(st.integers(min_value=0, max_value=59))
    second = draw(st.integers(min_value=0, max_value=59))
    date_s = "%04d-%02d-%02d" % (year, month, day)
    time_s = "%02d:%02d:%02d" % (hour, minute, second)
    if draw(st.booleans()):
        frac = draw(st.text(alphabet="0123456789", min_size=1, max_size=6))
        time_s += "." + frac
    record_production("date_time")
    if kind == "local_date":
        return date_s
    if kind == "local_time":
        return time_s
    delim = draw(st.sampled_from(["T", " ", "t"]))
    if kind == "local_dt":
        return date_s + delim + time_s
    offset = draw(st.sampled_from(["Z", "z", "+00:00", "-05:30", "+13:45"]))
    return date_s + delim + time_s + offset


def base_value_strategy():
    return st.one_of(
        string_value(),
        integer_value(),
        float_value(),
        bool_value(),
        date_time_value(),
    )


# ---------------------------------------------------------------------------
# Recursive containers: array_ and inline_table
# ---------------------------------------------------------------------------

@st.composite
def array_container(draw, children):
    with production("array_"):
        n = draw(st.integers(min_value=0, max_value=5))
        items = [draw(children) for _ in range(n)]
        multiline = draw(st.booleans())
        trailing_comma = items and draw(st.booleans())
        if multiline:
            if items:
                body = "\n  " + ",\n  ".join(items)
                body += ",\n" if trailing_comma else "\n"
            else:
                body = "\n" if draw(st.booleans()) else ""
            result = "[" + body + "]"
        else:
            body = ", ".join(items)
            if trailing_comma:
                body += ","
            result = "[" + body + "]"
    return result


@st.composite
def inline_table_container(draw, children):
    with production("inline_table"):
        n = draw(st.integers(min_value=0, max_value=4))
        pairs = []
        for _ in range(n):
            k = draw(key_strategy())
            v = draw(children)
            pairs.append("%s = %s" % (k, v))
        result = "{" + ", ".join(pairs) + "}"
    return result


def _container_extend(children):
    return st.one_of(
        array_container(children),
        inline_table_container(children),
    )


def value_strategy():
    return st.recursive(base_value_strategy(), _container_extend, max_leaves=20)


# ---------------------------------------------------------------------------
# Extreme-depth arrays / inline tables, targeting the known stack-overflow bug
# ---------------------------------------------------------------------------

@st.composite
def deep_array_value(draw):
    depth = draw(st.integers(min_value=100, max_value=30000))
    leaf = draw(st.sampled_from(["1", '"x"', "true", "1.5"]))
    with ExitStack() as stack:
        for _ in range(depth):
            stack.enter_context(production("array_"))
    return ("[" * depth) + leaf + ("]" * depth)


@st.composite
def deep_inline_table_value(draw):
    depth = draw(st.integers(min_value=100, max_value=30000))
    leaf = draw(st.sampled_from(["1", '"x"', "true"]))
    with ExitStack() as stack:
        for _ in range(depth):
            stack.enter_context(production("inline_table"))
    return ("{a=" * depth) + leaf + ("}" * depth)


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

@st.composite
def simple_key(draw):
    kind = draw(st.sampled_from(["unquoted", "basic", "literal"]))
    if kind == "unquoted":
        return draw(st.text(alphabet=UNQUOTED_KEY_CHARS, min_size=1, max_size=12))
    elif kind == "basic":
        return '"' + draw(_basic_string_content(multiline=False)) + '"'
    else:
        return "'" + draw(_literal_string_content(multiline=False)) + "'"


@st.composite
def dotted_key(draw):
    n = draw(st.integers(min_value=2, max_value=4))
    parts = [draw(simple_key()) for _ in range(n)]
    record_production("dotted_key")
    return ".".join(parts)


def key_strategy():
    return st.one_of(simple_key(), dotted_key())


# ---------------------------------------------------------------------------
# Comments, key_value, tables, expressions, document
# ---------------------------------------------------------------------------

@st.composite
def comment_text(draw):
    text = draw(st.text(
        alphabet=[c for c in map(chr, range(0x20, 0x7F))],
        max_size=25,
    ))
    return "#" + text


@st.composite
def key_value_line(draw):
    k = draw(key_strategy())
    choice = draw(st.integers(min_value=0, max_value=99))
    if choice < 88:
        v = draw(value_strategy())
    elif choice < 94:
        v = draw(deep_array_value())
    else:
        v = draw(deep_inline_table_value())
    record_production("key_value")
    return "%s = %s" % (k, v)


@st.composite
def standard_table_line(draw):
    k = draw(key_strategy())
    record_production("table")
    return "[" + k + "]"


@st.composite
def array_table_line(draw):
    k = draw(key_strategy())
    record_production("array_table")
    record_production("table")
    return "[[" + k + "]]"


def table_strategy():
    return st.one_of(standard_table_line(), array_table_line())


@st.composite
def expression(draw):
    kind = draw(st.sampled_from(
        ["key_value"] * 7 + ["table"] * 2 + ["comment_only"] * 2 + ["blank"] * 1
    ))
    has_comment = draw(st.booleans()) if kind != "comment_only" else True
    comment = draw(comment_text()) if has_comment else ""

    if kind == "key_value":
        body = draw(key_value_line())
    elif kind == "table":
        body = draw(table_strategy())
    elif kind == "comment_only":
        return comment
    else:
        return ""

    if comment:
        return body + " " + comment
    return body


@st.composite
def toml_document_strategy(draw):
    n = draw(st.integers(min_value=0, max_value=15))
    lines = [draw(expression()) for _ in range(n)]
    newline = "\r\n" if draw(st.booleans()) else "\n"
    doc = newline.join(lines)

    # Low-frequency semantic-conflict edge cases: these are syntactically
    # valid per the grammar (which has no uniqueness constraints) but are
    # known rejection points (duplicate key/table) or known tomlc99
    # superset-acceptances (array-of-table redefined as key) worth exercising.
    extra_choice = draw(st.integers(min_value=0, max_value=39))
    if extra_choice == 0:
        extra = "dup_key = 1" + newline + "dup_key = 2"
        doc = (doc + newline + extra) if doc else extra
    elif extra_choice == 1:
        extra = "[dup_tbl]" + newline + "x = 1" + newline + "[dup_tbl]" + newline + "y = 2"
        doc = (doc + newline + extra) if doc else extra
    elif extra_choice == 2:
        extra = "[[a]]" + newline + "b = 1" + newline + "a = 2"
        doc = (doc + newline + extra) if doc else extra

    return doc


def toml_document() -> st.SearchStrategy[str]:
    return toml_document_strategy()
