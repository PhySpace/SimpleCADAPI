"""canonical_bytes / canonical_hash: RFC 8785 straight from Python containers (bindings/python/bind_canonical.cpp).

The reference below is the algorithm of the `rfc8785` package the Python SDK uses (kept inline: this repo's
environment does not install it), plus the SDK's validation rules; the native functions must agree byte for byte
or answer None (outside the fast domain: the SDK then runs its own implementation and raises its own errors).
"""

from __future__ import annotations

import hashlib
import math
import random
import re
import struct

import pytest

import simplecadapi._cpp as scad

INT_MAX = 2**53 - 1
_ESCAPE = re.compile(r'[\x00-\x1f\\"\b\f\n\r\t]')
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
for _i in range(0x20):
    _ESCAPES.setdefault(chr(_i), f"\\u{_i:04x}")


class Rejected(ValueError):
    pass


def _float(f: float) -> str:
    if math.isnan(f) or math.isinf(f):
        raise Rejected("float")
    if f == 0:
        return "0"
    if f < 0:
        return "-" + _float(-f)
    text, exponent_text, exponent = str(f), "", 0
    q = text.find("e")
    if q > 0:
        exponent_text = text[q:]
        if exponent_text[2:3] == "0":
            exponent_text = exponent_text[:2] + exponent_text[3:]
        text = text[:q]
        exponent = int(exponent_text[1:])
    first, dot, last = text, "", ""
    q = text.find(".")
    if q > 0:
        dot, first, last = ".", text[:q], text[q + 1 :]
    if last == "0":
        dot, last = "", ""
    if 0 < exponent < 21:
        first += last
        last, dot, exponent_text = "", "", ""
        q = exponent - len(first)
        while q >= 0:
            q -= 1
            first += "0"
    elif -7 < exponent < 0:
        last = first + last
        first, dot, exponent_text = "0", ".", ""
        q = exponent
        while q < -1:
            q += 1
            last = "0" + last
    return f"{first}{dot}{last}{exponent_text}"


def reference(value) -> bytes:
    if value is None:
        return b"null"
    if isinstance(value, bool):
        return b"true" if value else b"false"
    if isinstance(value, int):
        if abs(value) > INT_MAX:
            raise Rejected("int")
        return str(value).encode()
    if isinstance(value, str):
        return b'"' + _ESCAPE.sub(lambda m: _ESCAPES[m.group(0)], value).encode("utf-8") + b'"'
    if isinstance(value, float):
        return _float(value).encode()
    if isinstance(value, (list, tuple)):
        return b"[" + b",".join(reference(item) for item in value) + b"]"
    if isinstance(value, dict):
        members = sorted(value.items(), key=lambda kv: kv[0].encode("utf-16be"))
        return b"{" + b",".join(reference(k) + b":" + reference(v) for k, v in members) + b"}"
    raise Rejected("type")


FLOATS = [0.0, -0.0, 1e21, 1e20, 1e-7, 1e-6, 1.5e16, 5e-324, 1.7976931348623157e308, 0.1, 1 / 3, 2.5e-5, 100.0,
          1e22, -1e21, 4.35, 1e15, 1e16, 1e17, 9007199254740993.0, 123456789012345680000.0, 1.0000000000000002]
ALPHABET = ["a", "Z", "0", "é", "퟿", "", "￿", "\U0001f600", "\U00010000", "\n", '"', "\\", "\x00",
            "\x1f", "\x7f", " ", "\u4e2d", "\b", " "]


def make(rnd: random.Random, depth: int = 0):
    c = rnd.random()
    if c < 0.1:
        return None
    if c < 0.18:
        return rnd.choice([True, False])
    if c < 0.38:
        return rnd.choice([0, -1, INT_MAX, -INT_MAX, INT_MAX + 1, 2**63, -(2**64), rnd.randint(-10**9, 10**9)])
    if c < 0.58:
        r = rnd.random()
        if r < 0.3:
            return rnd.choice(FLOATS)
        if r < 0.6:
            return struct.unpack("d", struct.pack("Q", rnd.getrandbits(64)))[0]
        return rnd.uniform(-1e5, 1e5)
    if c < 0.72:
        return "".join(rnd.choice(ALPHABET) for _ in range(rnd.randint(0, 5)))
    if depth > 4:
        return 7
    if c < 0.82:
        return [make(rnd, depth + 1) for _ in range(rnd.randint(0, 4))]
    if c < 0.88:
        return tuple(make(rnd, depth + 1) for _ in range(rnd.randint(0, 4)))
    return {"".join(rnd.choice(ALPHABET) for _ in range(rnd.randint(0, 4))): make(rnd, depth + 1)
            for _ in range(rnd.randint(0, 5))}


def test_fuzz_agrees_with_the_reference():
    rnd = random.Random(8785)
    native = rejected = 0
    for _ in range(5000):
        value = make(rnd)
        try:
            expected = reference(value)
        except Rejected:
            expected = None
        got = scad.canonical_bytes(value)
        if got is None:
            rejected += 1
            continue
        native += 1
        assert expected == got, repr(value)
    assert native > 3000 and rejected > 0


def test_hash_omits_top_level_keys_and_prefixes_sha256():
    value = {"b": [1, 2.5, None], "a": "x", "content_hash": "sha256:" + "0" * 64}
    draft = {"b": [1, 2.5, None], "a": "x"}
    expected = "sha256:" + hashlib.sha256(reference(draft)).hexdigest()
    assert scad.canonical_hash(value, ("content_hash",)) == expected
    assert scad.canonical_hash(draft, ()) == expected
    assert scad.canonical_hash(draft) == expected


def test_safe_ints_become_decimal_strings():
    value = {"n": 2**60, "m": [-(2**54), 3]}
    assert scad.canonical_bytes(value) is None
    assert scad.canonical_bytes(value, True) == b'{"m":["int:-18014398509481984",3],"n":"int:1152921504606846976"}'
    assert scad.canonical_hash(value, (), True) == "sha256:" + hashlib.sha256(
        b'{"m":["int:-18014398509481984",3],"n":"int:1152921504606846976"}'
    ).hexdigest()


@pytest.mark.parametrize(
    "value",
    [2**53, -(2**53), math.nan, math.inf, {1: 2}, {"a": object()}, "\ud800", {"\ud800": 1}, b"x", {"a": {1}}, {1, 2}],
)
def test_values_outside_the_domain_answer_none(value):
    assert scad.canonical_bytes(value) is None


def test_cycles_and_deep_nesting_answer_none():
    cyc: list = []
    cyc.append(cyc)
    assert scad.canonical_bytes(cyc) is None
    deep: list = []
    for _ in range(200):
        deep = [deep]
    assert scad.canonical_bytes(deep) is None


def test_key_order_is_utf16_code_unit_order():
    value = {"": 1, "\U00010000": 2, "￿": 3, "a": 4, "é": 5}
    assert scad.canonical_bytes(value) == reference(value)
    assert scad.canonical_bytes(value).index("\U00010000".encode()) < scad.canonical_bytes(value).index("".encode())
