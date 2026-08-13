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
# NOTE: '\/' removed this round -- it is not a standard TOML escape (only
# JSON allows it); even though the ANTLR ESC fragment happens to include it,
# there is no measured evidence tomlc99 accepts it, and it was an unforced
# source of reject risk on every basic string that rolled it. Every other
# escape here is a real TOML escape.
BASIC_ESCAPES = ['\\n', '\\t', '\\r', '\\"', '\\\\', '\\b', '\\f']
# Raw control bytes the grammar forbids inside a basic string but tomlc99 has
# been measured to accept -- confirmed superset gap, kept at healthy weight.
CONTROL_BYTES = ['\x01', '\x02', '\x03', '\x0b', '\x0c', '\x0d', '\x0e', '\x1f', '\x7f']


@st.composite
def _basic_string_content(draw, multiline=False):
    n = draw(st.integers(min_value=0, max_value=10))
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
    return draw(st.text(alphabet=alphabet, min_size=0, max_size=12))


# ---------------------------------------------------------------------------
# Terminal value productions
# ---------------------------------------------------------------------------

@st.composite
def string_value(draw):
    # Reweighted this round: "basic_invalid_escape" dropped from 1/8 (12.5%)
    # to 1/12 (~8.3%) of string instances -- it is a guaranteed reject every
    # time it fires, and with strings appearing across many key_values and
    # quoted keys per document, that weight alone was a large chunk of the
    # measured 28.8% acceptance rate. "basic_control_byte" (confirmed accept,
    # not a reject source) keeps its share.
    kind = draw(st.sampled_from([
        "basic", "basic", "basic", "basic",
        "basic_ml",
        "literal", "literal",
        "literal_ml",
        "basic_control_byte", "basic_control_byte",
        "basic_invalid_escape",
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
    elif kind == "basic_control_byte":
        # edge case: raw control byte inside a basic string.
        # Grammar forbids this; tomlc99 is known to accept it (measured
        # superset gap) -- does not cost acceptance.
        n = draw(st.integers(min_value=1, max_value=3))
        ctrls = "".join(draw(st.sampled_from(CONTROL_BYTES)) for _ in range(n))
        record_production("string")
        return '"' + ctrls + '"'
    else:
        # edge case: malformed escape (\x is not a recognized TOML escape).
        # Measured agreement case: tomlc99 rejects this, same as the grammar.
        # Kept at reduced frequency purely to keep the rejection path warm.
        hexdigits = draw(st.text(alphabet="0123456789abcdefABCDEF", min_size=2, max_size=2))
        record_production("string")
        return '"\\x' + hexdigits + '"'


@st.composite
def integer_value(draw):
    kind = draw(st.sampled_from(["dec", "dec", "dec", "hex", "oct", "bin", "leading_zero"]))
    if kind == "dec":
        sign = draw(st.sampled_from(["", "", "+", "-"]))
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
        # Grammar forbids; tomlc99 is known to accept it (superset gap,
        # not a reject source).
        digs = draw(st.text(alphabet="0123456789", min_size=1, max_size=4))
        record_production("integer")
        return "0" + digs


@st.composite
def float_value(draw):
    kind = draw(st.sampled_from(["frac", "frac", "exp", "fracexp", "inf", "nan", "dotless"]))
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
        # Grammar forbids; tomlc99 is known to accept it (superset gap).
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
# Recursive containers: array_ and inline_table (bounded breadth, real
# recursion via st.recursive -- kept modest here so the *bulk* of documents
# stay fast and well-formed; separate mid/deep-depth stress paths below fill
# the gap between st.recursive's shallow output and the extreme
# stack-overflow probes, and remain isolated single-value documents so a
# slow parse never drags down the accept rate of an unrelated well-formed
# document).
# ---------------------------------------------------------------------------

@st.composite
def array_container(draw, children):
    with production("array_"):
        n = draw(st.integers(min_value=0, max_value=3))
        items = [draw(children) for _ in range(n)]
        multiline = items and draw(st.integers(min_value=0, max_value=9)) < 3
        trailing_comma = items and draw(st.booleans())
        if multiline:
            body = "\n  " + ",\n  ".join(items)
            body += ",\n" if trailing_comma else "\n"
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
        n = draw(st.integers(min_value=0, max_value=3))
        pairs = []
        for i in range(n):
            base = "k%d" % i
            wrap = draw(st.sampled_from(["plain", "basic", "literal"]))
            if wrap == "basic":
                k = '"' + base + '"'
            elif wrap == "literal":
                k = "'" + base + "'"
            else:
                k = base
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
    # Real recursion (not a flattened fixed depth): st.recursive lets the
    # tree grow to varying depths across examples, bounded probabilistically
    # by max_leaves so ordinary documents stay fast and almost always parse.
    return st.recursive(base_value_strategy(), _container_extend, max_leaves=10)


# ---------------------------------------------------------------------------
# Mid-depth arrays / inline tables: fills the region between st.recursive's
# tiny trees and the extreme stack-overflow probes. Kept as isolated
# single-value documents so a slow parse never drags down the accept rate of
# an unrelated well-formed document.
# ---------------------------------------------------------------------------

MID_LEAVES = ["1", '"x"', "true", "1.5", "2021-01-01"]


def _mid_depth_strategy():
    return st.integers(min_value=10, max_value=400)


@st.composite
def mid_array_value(draw):
    depth = draw(_mid_depth_strategy())
    leaf = draw(st.sampled_from(MID_LEAVES))
    with ExitStack() as stack:
        for _ in range(depth):
            stack.enter_context(production("array_"))
    return ("[" * depth) + leaf + ("]" * depth)


@st.composite
def mid_inline_table_value(draw):
    depth = draw(_mid_depth_strategy())
    leaf = draw(st.sampled_from(MID_LEAVES))
    with ExitStack() as stack:
        for _ in range(depth):
            stack.enter_context(production("inline_table"))
    return ("{a=" * depth) + leaf + ("}" * depth)


@st.composite
def mid_stress_document(draw, kind):
    if kind == "array":
        v = draw(mid_array_value())
    else:
        v = draw(mid_inline_table_value())
    record_production("key_value")
    trailing_nl = draw(st.booleans())
    doc = "a = " + v
    if trailing_nl:
        doc += "\n"
    return doc


# ---------------------------------------------------------------------------
# Extreme-depth arrays / inline tables / mixed nesting, targeting the known
# stack-overflow bug. One crash signature has been confirmed so far; per the
# loop's own guidance -- steer away from bugs already found while keeping
# the regression warm -- this mode's overall share is unchanged from last
# round (it costs no acceptance, since these are always balanced/well-formed
# and the only outcomes are accept or crash, never reject).
# ---------------------------------------------------------------------------

DEEP_LEAVES = ["1", '"x"', "true", "1.5", "2021-01-01"]


def _deep_depth_strategy():
    return st.one_of(
        st.integers(min_value=500, max_value=15000),
        st.integers(min_value=15000, max_value=35000),
    )


@st.composite
def deep_array_value(draw):
    depth = draw(_deep_depth_strategy())
    leaf = draw(st.sampled_from(DEEP_LEAVES))
    with ExitStack() as stack:
        for _ in range(depth):
            stack.enter_context(production("array_"))
    return ("[" * depth) + leaf + ("]" * depth)


@st.composite
def deep_inline_table_value(draw):
    depth = draw(_deep_depth_strategy())
    leaf = draw(st.sampled_from(DEEP_LEAVES))
    with ExitStack() as stack:
        for _ in range(depth):
            stack.enter_context(production("inline_table"))
    return ("{a=" * depth) + leaf + ("}" * depth)


@st.composite
def deep_mixed_value(draw):
    depth = draw(_deep_depth_strategy())
    leaf = draw(st.sampled_from(DEEP_LEAVES))
    kinds = [draw(st.sampled_from(["array", "table"])) for _ in range(depth)]
    opens = []
    closes = []
    with ExitStack() as stack:
        for k in kinds:
            if k == "array":
                stack.enter_context(production("array_"))
                opens.append("[")
                closes.append("]")
            else:
                stack.enter_context(production("inline_table"))
                opens.append("{a=")
                closes.append("}")
        text = "".join(opens) + leaf + "".join(reversed(closes))
    return text


@st.composite
def deep_stress_document(draw, kind):
    if kind == "array":
        v = draw(deep_array_value())
    elif kind == "table":
        v = draw(deep_inline_table_value())
    else:
        v = draw(deep_mixed_value())
    record_production("key_value")
    trailing_nl = draw(st.booleans())
    doc = "a = " + v
    if trailing_nl:
        doc += "\n"
    return doc


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

@st.composite
def simple_key(draw):
    kind = draw(st.sampled_from(["unquoted", "unquoted", "basic", "literal"]))
    if kind == "unquoted":
        return draw(st.text(alphabet=UNQUOTED_KEY_CHARS, min_size=1, max_size=10))
    elif kind == "basic":
        return '"' + draw(_basic_string_content(multiline=False)) + '"'
    else:
        return "'" + draw(_literal_string_content(multiline=False)) + "'"


@st.composite
def build_key(draw, base_name):
    """Build a (possibly dotted) key whose leading segment is `base_name`.

    `base_name` is guaranteed unique among top-level expressions in the
    enclosing document, so this can never collide with another top-level
    key/table -- eliminating an entire class of guaranteed-real semantic
    rejects (duplicate key / key-vs-table conflicts) from the *unintentional*
    part of generation, while the deliberate low-frequency duplicate test
    below still exercises that rejection path directly.
    """
    wrap = draw(st.sampled_from(["plain", "basic", "literal"]))
    if wrap == "basic":
        head = '"' + base_name + '"'
    elif wrap == "literal":
        head = "'" + base_name + "'"
    else:
        head = base_name
    extra_n = draw(st.integers(min_value=0, max_value=2))
    segments = [head]
    for _ in range(extra_n):
        segments.append(draw(simple_key()))
    if extra_n > 0:
        record_production("dotted_key")
    return ".".join(segments)


# ---------------------------------------------------------------------------
# Comments, key_value, tables, expressions, document
# ---------------------------------------------------------------------------

@st.composite
def comment_text(draw):
    text = draw(st.text(
        alphabet=[c for c in map(chr, range(0x20, 0x7F))],
        max_size=20,
    ))
    return "#" + text


@st.composite
def key_value_line(draw, base_name):
    k = draw(build_key(base_name))
    v = draw(value_strategy())
    record_production("key_value")
    return "%s = %s" % (k, v)


@st.composite
def standard_table_line(draw, base_name):
    k = draw(build_key(base_name))
    record_production("table")
    return "[" + k + "]"


@st.composite
def array_table_line(draw, base_name):
    k = draw(build_key(base_name))
    record_production("array_table")
    record_production("table")
    return "[[" + k + "]]"


@st.composite
def table_strategy(draw, base_name):
    if draw(st.booleans()):
        return draw(standard_table_line(base_name))
    return draw(array_table_line(base_name))


# Named list of the deliberate near-valid-malformed / semantic-conflict
# probes. Kept as a lookup so the injection *frequency* (below) can be tuned
# independently of how many distinct probes exist.
_EXTRA_KINDS = [
    "dup_key", "dup_table", "redefine_arraytbl_as_key",
    "empty_comma_array", "trailing_comma_inline_table",
    "unterminated_string", "unterminated_array", "unterminated_table",
    "mismatched_array_table_close",
]


@st.composite
def normal_document(draw):
    n = draw(st.integers(min_value=0, max_value=12))
    kinds = [
        draw(st.sampled_from(
            ["key_value"] * 7 + ["table"] * 2 + ["comment_only"] * 2 + ["blank"] * 1
        ))
        for _ in range(n)
    ]
    need = sum(1 for k in kinds if k in ("key_value", "table"))
    if need > 0:
        base_names = draw(st.lists(
            st.text(alphabet=UNQUOTED_KEY_CHARS, min_size=1, max_size=10),
            min_size=need, max_size=need, unique=True,
        ))
    else:
        base_names = []
    name_iter = iter(base_names)

    lines = []
    for kind in kinds:
        has_comment = draw(st.booleans())
        comment = draw(comment_text()) if has_comment else ""
        if kind == "key_value":
            body = draw(key_value_line(next(name_iter)))
        elif kind == "table":
            body = draw(table_strategy(next(name_iter)))
        elif kind == "comment_only":
            lines.append(draw(comment_text()))
            continue
        else:
            lines.append("")
            continue
        if comment:
            lines.append(body + " " + comment)
        else:
            lines.append(body)

    newline = "\r\n" if draw(st.booleans()) else "\n"
    doc = newline.join(lines)

    # Low-frequency semantic-conflict / near-valid-malformed edge cases.
    # PREVIOUS ROUND: this fired on 9/24 (~37.5%) of documents, and since
    # 6 of those 9 are guaranteed rejects (unterminated tokens, dangling
    # commas, mismatched brackets), that alone accounted for roughly
    # 0.86 * 0.33 =~ 28 percentage points of forced reject -- almost the
    # entire gap between the measured 28.8% acceptance and a healthy rate.
    # Dropped here to a flat ~9% injection probability (1 in 11) with the
    # specific probe chosen uniformly from the same 9-item catalogue, so
    # every rejection/edge path stays warm but the bulk of documents are
    # no longer forced to fail at the front door.
    if draw(st.integers(min_value=0, max_value=10)) == 0:
        extra_kind = draw(st.sampled_from(_EXTRA_KINDS))
        if extra_kind == "dup_key":
            extra = "zzdup_key = 1" + newline + "zzdup_key = 2"
        elif extra_kind == "dup_table":
            extra = "[zzdup_tbl]" + newline + "x = 1" + newline + "[zzdup_tbl]" + newline + "y = 2"
        elif extra_kind == "redefine_arraytbl_as_key":
            # confirmed superset accept (not a reject source), kept for parity
            extra = "[[zzarrtbl]]" + newline + "b = 1" + newline + "zzarrtbl = 2"
        elif extra_kind == "empty_comma_array":
            extra = "zzemptycomma = [,]"
        elif extra_kind == "trailing_comma_inline_table":
            extra = "zztrail = {a = 1,}"
        elif extra_kind == "unterminated_string":
            extra = 'zzunterminated = "abc'
        elif extra_kind == "unterminated_array":
            extra = "zzunterm_arr = [1, 2"
        elif extra_kind == "unterminated_table":
            extra = "zzunterm_tbl = {a = 1"
        else:
            extra = "[[zzmismatch]" + newline + "a = 1"
        doc = (doc + newline + extra) if doc else extra

    return doc


@st.composite
def toml_document_strategy(draw):
    # Deep/mid stress modes cost no acceptance (they are always balanced,
    # well-formed nesting -- outcome is accept or crash, never reject), so
    # their weight is unchanged from last round; the acceptance-rate fix
    # this round lives entirely in normal_document's reduced malformed-probe
    # frequency and string_value's reduced invalid-escape weight.
    mode = draw(st.sampled_from(
        ["normal"] * 86
        + ["deep_array"] * 2
        + ["deep_table"] * 2
        + ["deep_mixed"] * 2
        + ["mid_array"] * 4
        + ["mid_table"] * 4
    ))
    if mode == "normal":
        return draw(normal_document())
    elif mode == "deep_array":
        return draw(deep_stress_document("array"))
    elif mode == "deep_table":
        return draw(deep_stress_document("table"))
    elif mode == "deep_mixed":
        return draw(deep_stress_document("mixed"))
    elif mode == "mid_array":
        return draw(mid_stress_document("array"))
    else:
        return draw(mid_stress_document("table"))


def toml_document() -> st.SearchStrategy[str]:
    return toml_document_strategy()
