"""Parity harness of the ops_geometry tests.

A *case* is a few lines of Python that build shapes with ``scad`` and put JSON-able facts in
``result`` (usually through ``describe``).  The very same text runs twice:

  * in the reference interpreter (``scad`` = simplecadapi, ``describe`` reads OCP), once, the
    answer being cached as tests/golden/ops_geometry_<name>.json;
  * here (``scad`` = simplecadapi._cpp, ``describe`` reads the native module).

so a case cannot test two different things on the two sides.  ``failure(call)`` describes the
SimpleCADError a call raises.
"""

from __future__ import annotations

import json
import textwrap

import simplecadapi._cpp as native
from simplecadapi._cpp import _native

from ref import GEOMETRY_REL, close, golden

# ---- the two sides of describe() ---------------------------------------------------------

_SHARED = '''
def failure(call):
    try:
        call()
    except scad.SimpleCADError as error:
        d = error.to_dict()
        out = {k: d[k] for k in ("operation", "what_happened", "possible_causes", "how_to_fix", "technical_details")}
        # OCP raises every StdFail_* as a plain Standard_Failure.
        if out["technical_details"] is not None:
            out["technical_details"] = out["technical_details"].replace("StdFail_NotDone:", "Standard_Failure:")
        return out
    except Exception as error:
        return {"exception": type(error).__name__}
    return {"raised": False}


def _finish(shape, kids_of, counts, bbox):
    kind = type(shape).__name__
    out = {"type": kind}
    kids = kids_of(shape)
    if kind in ("Solid", "Compound"):
        out["volume"] = shape.get_volume()
    if kind in ("Face", "Shell"):
        out["area"] = shape.get_area()
    if kind == "Edge":
        out["length"] = shape.get_length()
    if kind == "Wire":
        out["length"] = sum(edge.get_length() for edge in kids["edges"])
        out["closed"] = shape.is_closed()
    out["bbox"] = bbox(shape)
    out.update(counts(shape))
    out["tags"] = sorted(shape._list_tags(scope="local"))
    out["face_tags"] = sorted(sorted(f._list_tags(scope="local")) for f in kids["faces"])
    out["edge_tags"] = sorted(sorted(e._list_tags(scope="local")) for e in kids["edges"])
    out["track"] = shape.get_metadata("track")
    out["geo"] = shape.get_metadata("geo")
    return out
'''

REFERENCE_SIDE = (
    _SHARED
    + '''
from simplecadapi._cpp.occt.Bnd import Bnd_Box
from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib
from simplecadapi._cpp.occt.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from simplecadapi._cpp.occt.TopExp import TopExp
from simplecadapi._cpp.occt.TopTools import TopTools_IndexedMapOfShape


def _kids(shape):
    kind = type(shape).__name__
    faces = shape._iter_faces() if kind in ("Solid", "Shell", "Compound") else []
    edges = shape._iter_edges() if kind in ("Solid", "Shell", "Compound", "Face", "Wire") else []
    return {"faces": faces, "edges": edges}


def _counts(shape):
    out = {}
    for name, kind in (("faces", TopAbs_FACE), ("edges", TopAbs_EDGE), ("vertices", TopAbs_VERTEX)):
        shapes = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape.wrapped, kind, shapes)
        out[name] = shapes.Extent()
    return out


def _bbox(shape):
    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    return list(box.Get())


def describe(shape):
    return _finish(shape, _kids, _counts, _bbox)
'''
)


def _native_kids(shape):
    kind = type(shape).__name__
    faces = shape.faces() if kind in ("Solid", "Shell", "Compound") else []
    edges = shape.edges() if kind in ("Solid", "Shell", "Compound", "Face", "Wire") else []
    return {"faces": faces, "edges": edges}


_NAMESPACE: dict = {"scad": native}
exec(_SHARED, _NAMESPACE)


def native_describe(shape):
    return _NAMESPACE["_finish"](
        shape, _native_kids, _native.__dict__["_geometry_testing"].counts, _native.__dict__["_geometry_testing"].bbox
    )


def run_native(source: str):
    namespace = {"scad": native, "describe": native_describe, "failure": _NAMESPACE["failure"], "result": None}
    exec(textwrap.dedent(source), namespace)
    return json.loads(json.dumps(namespace["result"], default=float))


def mismatches(actual, expected, path="result", rel=GEOMETRY_REL, abs_=1e-9):
    """Where `actual` and `expected` differ, one line each (empty when they agree)."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        out = []
        # an error report of the reference with no guidance (a message-first family before its guidance was designed):
        # the port's report carries guidance, which is not compared
        unguided = (expected.get("possible_causes") == [] and expected.get("how_to_fix") == []
                    and "what_happened" in expected)
        for key in sorted(set(actual) | set(expected)):
            if unguided and key in ("possible_causes", "how_to_fix"):
                continue
            if key not in actual or key not in expected:
                out.append(f"{path}.{key}: {'missing' if key not in actual else 'unexpected'}")
            else:
                out += mismatches(actual[key], expected[key], f"{path}.{key}", rel, abs_)
        return out
    if close(actual, expected, rel, abs_):
        return []
    return [f"{path}: native {actual!r} != reference {expected!r}"]


def parity(name: str, source: str, rel: float = GEOMETRY_REL, abs_: float = 1e-9, prelude: str = ""):
    """Run `source` on both sides and assert that `result` agrees.  `prelude` is more shared helper code."""
    source = textwrap.dedent(prelude) + textwrap.dedent(source)
    expected = golden(f"ops_geometry_{name}", REFERENCE_SIDE + "\n" + source)
    found = mismatches(run_native(source), expected, rel=rel, abs_=abs_)
    assert not found, "\n".join(found)
    return expected
