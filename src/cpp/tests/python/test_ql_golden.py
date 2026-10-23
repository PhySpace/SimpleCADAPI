"""QL parity with the reference Python SDK.

One snippet of Python is run twice: by the reference interpreter (recorded once into
tests/golden/ql_*.json by `ref.golden`) and here, against the C++ port.  The shapes are built
separately (the port has no operators yet: raw OCCT boxes/cylinders/cuts with the same geometry);
every selector, predicate, key and error payload is the same code, so the comparison is exactly
"does the port's QL answer like the reference's".
"""

from __future__ import annotations

import textwrap

import pytest
from ref import close, golden

import simplecadapi._cpp as port
from simplecadapi._cpp.ql import _testing as raw

# --------------------------------------------------------------------------------------------- shapes
_REFERENCE_SHAPES = """
import os
os.environ["SCA_NO_DIAGNOSTIC_RENDER"] = "1"
box = scad.make_box_rsolid(10, 20, 30, bottom_face_center=(5, 10, 0))
rod = scad.make_cylinder_rsolid(2, 5)
split = scad.cut_rsolid(
    scad.make_cylinder_rsolid(10, 20),
    scad.cut_rsolid(
        scad.make_cylinder_rsolid(12, 6, bottom_face_center=(0, 0, 7)),
        scad.make_cylinder_rsolid(9, 10, bottom_face_center=(0, 0, 5)),
    ),
)
notched = scad.cut_rsolid(
    scad.make_cylinder_rsolid(1.5, 4.0, bottom_face_center=(0, 0, -2)),
    scad.make_box_rsolid(4, 4, 4, bottom_face_center=(0, 0, 0.25)),
)
"""


def port_shapes():
    return {
        "box": raw.box_at((0, 0, 0), 10, 20, 30),
        "rod": raw.cylinder_at((0, 0, 0), 2, 5),
        "split": raw.cut(
            raw.cylinder_at((0, 0, 0), 10, 20),
            raw.cut(raw.cylinder_at((0, 0, 7), 12, 6), raw.cylinder_at((0, 0, 5), 9, 10)),
        ),
        "notched": raw.cut(raw.cylinder_at((0, 0, -2), 1.5, 4.0), raw.box_at((-2, -2, 0.25), 4, 4, 4)),
    }


def run_port(snippet: str):
    namespace = {"scad": port, "result": None, **port_shapes()}
    exec(snippet, namespace)
    return namespace["result"]


def compare(name: str, *parts: str):
    snippet = "\n".join(textwrap.dedent(part) for part in parts)
    expected = golden(name, _REFERENCE_SHAPES + snippet)
    actual = run_port(snippet)
    assert close(actual, expected), (actual, expected)


# --------------------------------------------------------------------------------------------- payloads
def test_payloads_match_reference():
    compare(
        "ql_payloads",
        """
        ql = scad.ql
        face_a = ql.faces().where(ql.tag("face.top"))
        face_b = ql.faces().where(ql.tag("face.front"))
        result = {
            "edge_selector": ql.edges().where(ql.prop("geom.type", "==", "CIRCLE")).order_by(ql.key("geom.center.z")).take(1).exactly(1).to_dict(),
            "chain": (
                ql.faces()
                .where(ql.and_(ql.tag("a.*", scope="local"), ql.not_(ql.meta("x.y", ">=", 3))))
                .where(ql.or_(ql.op("cut", "modified"), ql.origin("tool"), ql.output_role("A.B")))
                .order_by(ql.value("geo.area", 0.0), desc=True)
                .order_by(ql.center_axis("x"))
                .take(3).at_least(1).at_most(4)
                .from_source("node_1", 2)
                .boundary("edge")
                .where(ql.curve_type("line"))
                .to_dict()
            ),
            "incident": ql.faces().where(ql.tag("a")).boundary("edge").incident_to(face_a, face_b, distinct=True).incident_face_count(exactly=2).exactly(1).to_dict(),
            "shared": face_a.shared_boundary(face_b).exactly(1).to_dict(),
            "role": ql.role("section").to_dict(),
            "source": [ql.source_binding("b1").to_dict(), ql.source_topology("face_3").to_dict()],
            "keys": [k.to_dict() for k in (ql.value("a.b"), ql.key("geom.area", 0), ql.geo("volume", 1.5), ql.center_axis("Y"))],
            "bare": {
                "faces": ql.faces().to_dict(), "wires": ql.wires().to_dict(), "vertices": ql.vertices().to_dict(),
                "solids": ql.solids().to_dict(), "shells": ql.shells().to_dict(),
            },
            "wire_walk": ql.solids().boundary("face").boundary("wire").boundary("vertex").to_dict(),
        }
        """,
    )


# --------------------------------------------------------------------------------------------- resolution
_QUERIES = """
    ql = scad.ql

    def num(v):
        return None if v is None else round(float(v), 5)

    def describe(shape):
        centre = [num(ql.key("geom.center." + a)(shape)) for a in "xyz"]
        measures = [num(ql.key(p)(shape)) for p in ("geom.area", "geom.length", "geom.volume")]
        return [type(shape).__name__, centre, measures]

    def ordered(selector, scope):
        return [describe(s) for s in selector.resolve(scope)]

    def unordered(selector, scope):
        return sorted(ordered(selector, scope), key=repr)

    def failure(selector, scope):
        try:
            selector.resolve(scope)
        except ValueError as exc:
            data = exc.to_dict()
            data.pop("evidence", None)
            return data
        return None

    top = ql.faces().where(ql.prop("geom.normal.z", ">", 0.9)).order_by(ql.key("geom.center.z"), desc=True).take(1).exactly(1)
    front = ql.faces().where(ql.prop("geom.normal.y", "<", -0.9)).exactly(1)
"""


def test_resolution_matches_reference():
    compare(
        "ql_resolution",
        _QUERIES,
        """
        result = {
            "top": ordered(top, box),
            "faces_by_z_x": ordered(ql.faces().order_by(ql.key("geom.center.z"), desc=True).order_by(ql.key("geom.center.x")), box),
            "edges": unordered(ql.edges(), box),
            "vertices": unordered(ql.vertices(), box),
            "wires_of_solid": ordered(ql.wires(), box),
            "top_wire": ordered(top.boundary("wire"), box),
            "top_edges": unordered(top.boundary("wire").where(ql.prop("topo.loop_role", "==", "outer")).boundary("edge"), box),
            "top_vertices": unordered(top.boundary("vertex"), box),
            "shared": unordered(top.shared_boundary(front), box),
            "incident": unordered(ql.edges().incident_to(top, front, distinct=True).incident_face_count(exactly=2), box),
            "incident_loose": unordered(ql.edges().incident_to(top, top), box),
            "incident_distinct_same": unordered(ql.edges().incident_to(top, top, distinct=True), box),
            "limit_zero": ordered(ql.faces().take(0), box),
            "rod_circles": ordered(ql.edges().where(ql.curve_type("circle")).order_by(ql.key("geom.center.z")), rod),
            "rod_surfaces": sorted(ql.key("geom.type")(f) for f in ql.faces().resolve(rod)),
            "rod_family": sorted(ql.key("geom.family")(s) for s in ql.faces().boundary("edge").resolve(rod)),
            "split_cylinders": unordered(ql.faces().where(ql.surface_type("CYLINDER")), split),
            "split_planes_by_z": ordered(ql.faces().where(ql.surface_type("PLANE")).order_by(ql.key("geom.center.z")).order_by(ql.key("geom.area"), desc=True), split),
            "split_vertices": unordered(ql.vertices(), split),
            "notched_top_edges": unordered(
                ql.faces().where(ql.surface_type("PLANE")).where(ql.prop("geom.normal.z", ">", 0.9))
                .order_by(ql.key("geom.center.z"), desc=True).take(1).exactly(1)
                .boundary("wire").where(ql.prop("topo.loop_role", "==", "outer")).take(1).exactly(1).boundary("edge"), notched),
            "bbox_filter": unordered(ql.faces().where(ql.and_(ql.prop("geom.bbox.min.x", "==", 0), ql.prop("geom.bbox.max.x", "==", 0))), box),
            "missing_props": [
                unordered(ql.faces().where(ql.prop("geom.length", ">", 0)), box),
                unordered(ql.edges().where(ql.prop("geom.area", ">", 0)), box),
                unordered(ql.solids().where(ql.prop("geom.center.x", ">", -100)), box),
                unordered(ql.faces().where(ql.prop("nothing.here", "!=", 3)), box),
            ],
        }
        """,
    )


def test_tags_and_metadata_match_reference():
    compare(
        "ql_tags_meta",
        _QUERIES,
        """
        faces = ql.faces().resolve(box)
        faces[0]._apply_tag("role.x", propagate=False)
        faces[1]._apply_tag("role.y", propagate=False)
        box._apply_tag("group.all", propagate=True)
        box.set_metadata("geo", {"type": "box", "size": {"x": 10, "y": 20.5}, "label": "A"})
        faces[2].set_metadata("track", {"op": "make_cut_rsolid", "events": ["modified"], "origin_roles": ["tool"], "result_role": "cut.wall"})
        result = {
            "role_any": len(ql.faces().where(ql.tag("role.*")).resolve(box)),
            "role_exact": len(ql.faces().where(ql.tag("role.x")).resolve(box)),
            "role_family": len(ql.faces().where(ql.role("x")).resolve(box)),
            "inherited": [len(ql.faces().where(ql.tag("group.all", scope=s)).resolve(box)) for s in ("local", "inherited", "effective")],
            "meta_gt": len(ql.solids().where(ql.meta("geo.size.y", ">", 20)).resolve(box)),
            "meta_eq_mixed_numeric": len(ql.solids().where(ql.meta("geo.size.x", "==", 10.0)).resolve(box)),
            "meta_incomparable": len(ql.solids().where(ql.meta("geo.label", ">", 3)).resolve(box)),
            "meta_missing_eq_none": len(ql.faces().where(ql.meta("geo.type", "==", None)).resolve(box)),
            "meta_missing_ne": len(ql.faces().where(ql.meta("geo.type", "!=", "box")).resolve(box)),
            "prop_metadata_path": len(ql.solids().where(ql.prop("geo.size.x", ">=", 10)).resolve(box)),
            "prop_meta_prefix": len(ql.solids().where(ql.prop("meta.geo.type", "==", "box")).resolve(box)),
            "op_event": len(ql.faces().where(ql.op("cut", "modified")).resolve(box)),
            "op_other_event": len(ql.faces().where(ql.op("cut", "generated")).resolve(box)),
            "origin": len(ql.faces().where(ql.origin("tool")).resolve(box)),
            "output_role": len(ql.faces().where(ql.output_role("cut.wall")).resolve(box)),
            "order_by_value": [num(ql.value("geo.area")(f)) for f in ql.faces().order_by(ql.value("geo.area"), desc=True).resolve(box)],
            "select": [
                len(ql.select(ql.faces().resolve(box)).where(ql.tag("role.*")).all()),
                ql.select([3, 1, 2]).order_by(lambda v: v, desc=True).all(),
                ql.select([]).first(),
            ],
        }
        """,
    )


# --------------------------------------------------------------------------------------------- diagnostics
def test_cardinality_failures_match_reference():
    compare(
        "ql_failures",
        _QUERIES,
        """
        result = {
            "exactly_box": failure(ql.faces().where(ql.prop("geom.type", "==", "PLANE")).take(2).exactly(1), box),
            "zero_sphere": failure(ql.faces().where(ql.surface_type("SPHERE")).at_least(1), split),
            "split_group": failure(ql.faces().where(ql.surface_type("CYLINDER")).exactly(1), split),
            "at_most_edges": failure(ql.edges().at_most(3), box),
            "vertices": failure(ql.vertices().exactly(2), box),
            "solids": failure(ql.solids().exactly(2), box),
            "capped_near_misses": failure(ql.edges().where(ql.prop("geom.center.z", "<", 0.1)).exactly(1), box),
            "rod_edges": failure(ql.edges().exactly(1), rod),
            "split_edges": failure(ql.edges().exactly(1), split),
            "plain_faces_no_group": failure(ql.faces().exactly(5), box),
        }
        """,
    )


def test_evidence_provider_receives_the_reference_arguments():
    seen = {}

    def provider(scope, matched, target_kind, dedup_key, near_misses):
        seen.update(kind=target_kind, key=dedup_key, matched=len(matched), near=len(near_misses))
        return [{"kind": "render", "path": "/tmp/x.png", "view": "default", "caption": "c", "symbols": {"F1": "hit"}}]

    port.ql._set_evidence_provider(provider)
    try:
        shapes = port_shapes()
        with pytest.raises(port.SimpleCADError) as info:
            port.ql.faces().where(port.ql.surface_type("CYLINDER")).exactly(1).resolve(shapes["split"])
    finally:
        port.ql._set_evidence_provider(None)

    assert seen == {"kind": "face", "key": ("ql", "face", "exactly", 1, 3), "matched": 3, "near": 3}
    evidence = info.value.to_dict()["evidence"]
    assert evidence == [{"kind": "render", "path": "/tmp/x.png", "view": "default", "caption": "c", "symbols": {"F1": "hit"}}]
    assert "Evidence:\n- render view 'default': /tmp/x.png (c)\n  symbols: F1=hit" in str(info.value)
