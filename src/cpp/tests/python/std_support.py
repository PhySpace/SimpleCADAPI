"""Shared plumbing of the std parity tests.

Same scheme as ops_features_support: a snippet written against `scad` runs in the reference
interpreter (recorded once into tests/golden/std_<name>.json) and against the port, and both
must give the same JSON.  The snippets have `describe` (volume, area, counts, bbox, tags),
`meta` (a metadata dict), `refuse` (the ValueError text of a call) and `graph_summary` (what a
recording session saw) on top of the ops_features prelude.
"""

from __future__ import annotations

import textwrap

from ops_features_support import PRELUDE as _BASE_PRELUDE
from ops_features_support import _diff
from ref import GEOMETRY_REL, close, golden

import simplecadapi._cpp as port

PRELUDE = _BASE_PRELUDE + '''
std = scad.std

def meta(shape, key):
    return shape.get_metadata(key)

def refuse(call):
    """The exception a call raises, as [type name, message] (errors of the operators carry guidance)."""
    try:
        call()
    except scad.SimpleCADError as e:
        return ["SimpleCADError", e.to_dict()["operation"], e.to_dict()["technical_details"]]
    except Exception as e:
        return [type(e).__name__, str(e)]
    return None

def nodes_of(session):
    return session.graph.to_dict()["nodes"]

def graph_summary(session):
    """Operation names in order, and which recorded nodes carry a topology delta."""
    nodes = nodes_of(session)
    return {
        "ops": [n["op"] for n in nodes],
        "with_delta": sorted({n["op"] for n in nodes if "topo_delta" in n}),
    }
'''


def run_port(snippet: str):
    namespace = {"scad": port, "result": None}
    exec(PRELUDE + snippet, namespace)
    return namespace["result"]


PHASE_CANDIDATES = (0.0, 15.0, 30.0, 45.0, 60.0, 90.0, 120.0, 135.0, 150.0, 165.0, 180.0, 210.0, 240.0, 270.0, 300.0, 330.0)
PHASE_FIELDS = ("thread_phase_degrees", "faces", "edges", "rotations", "cuts", "unions")


def _without(value, keys):
    if isinstance(value, dict):
        return {k: _without(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_without(v, keys) for v in value]
    return value


def _phases(value):
    if isinstance(value, dict):
        yield from ([value["thread_phase_degrees"]] if "thread_phase_degrees" in value else [])
        for item in value.values():
            yield from _phases(item)
    elif isinstance(value, list):
        for item in value:
            yield from _phases(item)


def compare(name: str, *parts: str, rel: float = GEOMETRY_REL, abs_: float = 1e-7, phase_searched: bool = False):
    """Run the snippet on the port and on the reference and require the same JSON.

    ``phase_searched``: the modeled-thread builders try candidate phase angles and keep the first one whose Boolean
    comes out valid.  Which candidate that is depends on last-bit floating-point differences of the helix sweep (the
    platform, the libm), so the angle and the topology counts it implies are not part of the contract: they are dropped
    from the comparison, the angle must still be a real candidate, and the measures (volume, area, bounding box) are
    compared at a looser tolerance because a different phase cuts the same thread at a different turn.
    """
    snippet = "\n".join(textwrap.dedent(part) for part in parts)
    expected = golden("std_" + name, PRELUDE + snippet)
    actual = run_port(snippet)
    if phase_searched:
        assert all(angle in PHASE_CANDIDATES for angle in _phases(actual)), list(_phases(actual))
        actual, expected = _without(actual, PHASE_FIELDS), _without(expected, PHASE_FIELDS)
        rel = max(rel, 5e-3)
    assert close(actual, expected, rel, abs_), _diff(actual, expected)
