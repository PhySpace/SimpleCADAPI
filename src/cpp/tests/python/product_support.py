"""Parity harness of the product tests.

A *case* is a few lines of Python that build product values with ``scad`` and put JSON-able facts in
``result`` -- usually the ``to_dict()`` of what they built.  The very same text runs in the
reference interpreter (``scad`` = simplecadapi, once, cached as tests/golden/product_<name>.json) and
here (``scad`` = simplecadapi._cpp), so a case cannot test two different things on the two sides.

``failure(call)`` describes the error a call raises (the SimpleCADError's guidance, or the plain
exception's type and text); ``top_face(box)`` / ``pick_edge(box, ...)`` pick sub-shapes with the
indexed ``get_faces(i)`` / ``get_edges(i)`` that both sides have.
"""

from __future__ import annotations

import json
import textwrap

import simplecadapi._cpp as _cpp


class _Native:
    """The C++ module as the SDK serves it: ``GraphSession`` is the SDK's session (it carries the tolerance/frame graphs
    and the hooks the recording wrappers use); every other name is the C++ module's own."""

    def __getattr__(self, name):
        if name == "GraphSession":
            from simplecadapi._glue.session import GraphSession

            return GraphSession
        return getattr(_cpp, name)


native = _Native()

from ref import close, golden

_PRELUDE = '''
import math


def _guidance(error):
    d = error.to_dict()
    out = {k: d[k] for k in ("operation", "what_happened", "possible_causes", "how_to_fix", "technical_details")}
    for key in ("measurements", "repair", "inventory"):
        out[key] = d.get(key) or []
    return out


def failure(call):
    try:
        call()
    except scad.SimpleCADError as error:
        return _guidance(error)
    except Exception as error:
        return {"exception": type(error).__name__, "message": str(error)}
    return {"raised": False}


def top_face(box):
    for index in range(6):
        face = box.get_faces(index)
        if face.get_normal_at().z > 0.99:
            return face
    raise AssertionError("no top face")


def vertical_edge(box):
    for index in range(12):
        edge = box.get_edges(index)
        start, end = edge.get_start_vertex().get_coordinates(), edge.get_end_vertex().get_coordinates()
        if abs(start[0] - end[0]) < 1e-9 and abs(start[1] - end[1]) < 1e-9:
            return edge
    raise AssertionError("no vertical edge")


def axis_part(part_id, origin=(0.0, 0.0, 0.0), size=1.0):
    part = scad.make_part_rpart(part_id, scad.make_box_rsolid(size, size, size))
    placement = scad.make_placement_rplacement(origin=origin)
    return scad.add_connector_rpart(part, scad.make_placement_connector_rconnector("axis", placement))


def ref(component, connector="axis"):
    return scad.make_connector_ref_rconnectorref(component, connector)


def add(assembly, part, component_id, origin=None):
    placement = scad.identity_placement_rplacement() if origin is None else scad.make_placement_rplacement(origin=origin)
    return scad.add_component_rassembly(assembly, part, component_id, placement)


def solid_centers(compound):
    """Mean face centre of every solid (the reference Solid has no get_center)."""
    solids = compound._iter_solids() if hasattr(compound, "_iter_solids") else compound.solids()
    out = []
    for solid in solids:
        faces = solid._iter_faces() if hasattr(solid, "_iter_faces") else solid.faces()
        centers = [face.get_center() for face in faces]
        out.append([sum(getattr(c, axis) for c in centers) / len(centers) for axis in "xyz"])
    return sorted(out)


def placements(assembly):
    return {c.component_id: c.placement.to_dict() for c in assembly.components}


def z_angle(placement):
    return math.degrees(math.atan2(placement.x_axis[1], placement.x_axis[0]))


def solved_summary(solved):
    return {
        "placements": placements(solved),
        "report": solved._get_runtime("constraint_report"),
        "authored": solved._get_runtime("assembly.authored_component_placements"),
    }
'''


def mismatches(actual, expected, path="result", rel=1e-6, abs_=1e-9):
    """Where `actual` and `expected` differ, one line each (empty when they agree)."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        out = []
        for key in sorted(set(actual) | set(expected)):
            if key not in actual or key not in expected:
                out.append(f"{path}.{key}: {'missing' if key not in actual else 'unexpected'}")
            else:
                out += mismatches(actual[key], expected[key], f"{path}.{key}", rel, abs_)
        return out
    if close(actual, expected, rel, abs_):
        return []
    return [f"{path}: native {actual!r} != reference {expected!r}"]


def run_native(source: str):
    namespace = {"scad": native, "result": None}
    exec(_PRELUDE, namespace)
    exec(textwrap.dedent(source), namespace)
    return json.loads(json.dumps(namespace["result"], default=float))


def parity(name: str, source: str, rel: float = 1e-6, abs_: float = 1e-9, ignore=()):
    """Run `source` on both sides and assert that `result` agrees; keys in `ignore` are dropped first."""
    source = textwrap.dedent(source)
    expected = golden(f"product_{name}", _PRELUDE + "\n" + source)
    actual = run_native(source)
    found = mismatches(_without(actual, ignore), _without(expected, ignore), rel=rel, abs_=abs_)
    assert not found, "\n".join(found)
    return expected


def _without(value, keys):
    if isinstance(value, dict):
        return {k: _without(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_without(v, keys) for v in value]
    return value
