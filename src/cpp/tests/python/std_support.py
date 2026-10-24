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


def compare(name: str, *parts: str, rel: float = GEOMETRY_REL, abs_: float = 1e-7):
    snippet = "\n".join(textwrap.dedent(part) for part in parts)
    expected = golden("std_" + name, PRELUDE + snippet)
    actual = run_port(snippet)
    assert close(actual, expected, rel, abs_), _diff(actual, expected)
