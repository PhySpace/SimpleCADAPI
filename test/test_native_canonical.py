"""The native canonical-JSON walker is byte-identical to the Python implementation.

``artifacts.canonical.canonical_bytes`` / ``content_hash`` (validate recursively, then rfc8785) were ~25% of an
arm6 build; on the native backend they run in C++ and fall back to the Python code for anything outside the
fast domain, so the errors are the Python ones.  Checked on values recorded from a real arm6 build (geometry
interface descriptors, feature graphs, definitions, topology snapshots) and on a seeded fuzz of numbers,
unicode and nesting, including every value the validator rejects.
"""

from __future__ import annotations

import enum
import gzip
import hashlib
import json
import math
import os
import random
import struct
from pathlib import Path

import pytest

import rfc8785  # noqa: E402

from simplecadapi.artifacts import canonical as C  # noqa: E402
from simplecadapi.artifacts import geometry_interface as G  # noqa: E402

CORPUS = Path(__file__).parent / "fixtures" / "native_canonical_corpus.json.gz"


def python_bytes(value):
    C.validate_json_value(value)
    return C.canonical_json_bytes(value)


def python_hash(value, omit):
    draft = {key: item for key, item in value.items() if key not in omit}
    return C.sha256_bytes(python_bytes(draft))


def outcome(call):
    try:
        return ("ok", call())
    except Exception as error:  # noqa: BLE001 - the type and text are what is compared
        return ("err", type(error), str(error))


def test_native_walker_is_active():
    assert C._NATIVE is not None


def test_recorded_arm6_values_hash_identically():
    corpus = json.loads(gzip.decompress(CORPUS.read_bytes()))
    assert len(corpus) > 1000
    for entry in corpus:
        value = json.loads(entry["json"])
        if entry["safe_ints"]:
            value = G._json_safe(value)
        omit = tuple(entry["omit"])
        if omit:
            value = {key: item for key, item in value.items() if key not in omit}
        native = C._NATIVE.canonical_bytes(value)
        assert native is not None and len(native) == entry["length"]
        assert hashlib.sha256(native).hexdigest() == entry["bytes_sha256"]
        assert native == python_bytes(value)
        assert C.content_hash(value, omit=()) == "sha256:" + entry["bytes_sha256"]


def test_geometry_interface_hash_matches_python_json_safe_path():
    for payload in (
        {"a": 2**60, "b": [-(2**70), (5, 2**54)], "c": 1.5},
        {"kind": "body", "geometry": ("body", 12, (1, 2, 3), (-2**53, 4, 5, 6, 7, 8))},
        [True, 1.0],
        2**53,
    ):
        assert G._hash(payload) == C.content_hash(G._json_safe(payload), omit=())


FLOATS = [
    0.0, -0.0, 1e21, 1e20, 1e-7, 1e-6, 1.5e16, 5e-324, 1.7976931348623157e308, 0.1, 1 / 3, 2.5e-5, 100.0,
    1e22, -1e21, 4.35, 1e15, 1e16, 1e17, 9007199254740993.0, 123456789012345680000.0, 0.000001, 1.0000000000000002,
]
ALPHABET = ["a", "Z", "0", "é", "ÿ", "퟿", "", "￿", "\U0001f600", "\U00010000", "\n", "\t",
            '"', "\\", "\x00", "\x1f", "\x7f", " ", "中", "\b", "\f", "\r", " "]


def random_float(rnd):
    choice = rnd.random()
    if choice < 0.25:
        return rnd.choice(FLOATS)
    if choice < 0.6:
        return struct.unpack("d", struct.pack("Q", rnd.getrandbits(64)))[0]
    if choice < 0.85:
        return rnd.uniform(-1e6, 1e6)
    return round(rnd.uniform(-100, 100), rnd.randint(0, 9))


def random_value(rnd, depth=0, hostile=False):
    choice = rnd.random()
    if choice < 0.1:
        return None
    if choice < 0.18:
        return rnd.choice([True, False])
    if choice < 0.38:
        return rnd.choice([0, 1, -1, 9007199254740991, -9007199254740991, 9007199254740992, -9007199254740992, 2**63,
                           -(2**64), rnd.randint(-10**6, 10**6), rnd.randint(-(2**62), 2**62)])
    if choice < 0.58:
        if hostile and rnd.random() < 0.15:
            return rnd.choice([math.nan, math.inf, -math.inf])
        return random_float(rnd)
    if choice < 0.72:
        text = "".join(rnd.choice(ALPHABET) for _ in range(rnd.randint(0, 6)))
        return text if not (hostile and rnd.random() < 0.05) else text + "\ud800"
    if depth > 5:
        return rnd.randint(0, 5)
    if choice < 0.82:
        return [random_value(rnd, depth + 1, hostile) for _ in range(rnd.randint(0, 4))]
    if choice < 0.88:
        return tuple(random_value(rnd, depth + 1, hostile) for _ in range(rnd.randint(0, 4)))
    keys = ["".join(rnd.choice(ALPHABET) for _ in range(rnd.randint(0, 4))) for _ in range(rnd.randint(0, 5))]
    members = {key: random_value(rnd, depth + 1, hostile) for key in keys}
    if hostile and rnd.random() < 0.05:
        members[rnd.choice([1, None, 2.5])] = 1
    return members


def test_fuzz_matches_python_bytes_and_errors():
    rnd = random.Random(20261022)
    fast = 0
    for index in range(6000):
        value = random_value(rnd, hostile=index % 3 == 0)
        expected = outcome(lambda: python_bytes(value))
        assert outcome(lambda: C.canonical_bytes(value)) == expected
        native = C._NATIVE.canonical_bytes(value)
        if native is not None:
            fast += 1
            assert expected == ("ok", native)
        if isinstance(value, dict) and value:
            omit = (next(iter(value)), "content_hash")
            expected = outcome(lambda: python_hash(value, omit))
            assert outcome(lambda: C.content_hash(value, omit=omit)) == expected
    assert fast > 3000


def test_error_cases_keep_their_python_type_and_message():
    cyclic = []
    cyclic.append(cyclic)
    self_dict: dict = {}
    self_dict["a"] = self_dict

    class Color(str, enum.Enum):
        RED = "red"

    class Level(enum.IntEnum):
        TWO = 2

    for value in (
        cyclic, self_dict, {1: 2}, {"a": object()}, "\ud800", {"\ud800": 1}, 2**53, -(2**53), math.nan, math.inf,
        [[math.nan]], {"k": [1, {"z": -math.inf}]}, b"bytes", {"a": {1, 2}},
    ):
        assert outcome(lambda: C.canonical_bytes(value)) == outcome(lambda: python_bytes(value)), repr(value)
    for value in ({Color.RED: Level.TWO, "k": Color.RED}, {"a": 1}):
        assert C.canonical_bytes(value) == python_bytes(value)
    deep: list = []
    for _ in range(300):
        deep = [deep]
    assert C.canonical_bytes(deep) == python_bytes(deep)
    assert C.canonical_bytes({"": 1, "\U00010000": 2, "￿": 3, "a": 4}) == (
        b'{"a":4,"\xf0\x90\x80\x80":2,"\xee\x80\x80":1,"\xef\xbf\xbf":3}'
    )
