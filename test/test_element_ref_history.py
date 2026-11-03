"""Stable element references resolved through recorded history (spike, design-docs/stable-refs-design.md).

Each case is one of the known failures of today's naming channels (a plain face tag dies at the next
operation; an op-kwarg cap tag dies at a fillet; a split face has no answer), shown failing on the tag
channel and resolved by ``simplecadapi.topology.element_ref`` with the right status and the right
entities.  The audit cases at the end pin, per operation family, what history the kernel records today.
"""

from __future__ import annotations

import math

import pytest

import simplecadapi as scad
from simplecadapi import ql
from simplecadapi.topology import element_ref as er


def _z(lo: float, hi: float):
    return ql.and_(ql.prop("geom.center.z", ">=", lo), ql.prop("geom.center.z", "<=", hi))


def _faces_at(shape, z: float):
    return ql.faces().where(_z(z - 1e-6, z + 1e-6)).where(ql.prop("geom.type", "==", "PLANE")).resolve(shape)


def _edges_at(shape, z: float):
    return ql.edges().where(_z(z - 1e-6, z + 1e-6)).resolve(shape)


def _tagged(shape, tag: str) -> int:
    return len(ql.faces().where(ql.tag(tag)).resolve(shape))


def _box_with_top_anchor():
    box = scad.make_box_rsolid(40, 20, 10)
    (top,) = _faces_at(box, 10)
    anchor = er.anchor_of(top)
    box = scad.apply_tag_rselection(box, [top], "user.top")
    return box, anchor


# ---------------------------------------------------------------------------
# The known failures
# ---------------------------------------------------------------------------


def test_plain_face_tag_after_a_boolean():
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        cut = scad.cut_rsolid(box, scad.make_cylinder_rsolid(3, 30))

        assert _tagged(cut, "user.top") == 1  # the tag is a view over the same history (it used to die here)

        r = er.resolve(anchor, cut)
        assert r.status == "ok"
        (face,) = r.entities
        assert face.get_center().z == pytest.approx(10.0)
        assert face.get_area() == pytest.approx(800 - math.pi * 9, rel=1e-6)
        assert [hop["op"] for hop in r.hops][-1] == "make_cut_rsolid"


def test_plain_face_tag_after_a_fillet():
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        filleted = scad.fillet_rsolid(box, _edges_at(box, 10), 2.0)

        assert _tagged(filleted, "user.top") == 1

        r = er.resolve(anchor, filleted)
        assert r.status == "ok"
        (face,) = r.entities
        assert face.get_center().z == pytest.approx(10.0)
        assert face.get_area() == pytest.approx(36 * 16)  # the top shrunk by the 2 mm blends


def test_extrude_cap_after_a_fillet_of_its_edges():
    with scad.GraphSession():
        solid = scad.extrude_rsolid(scad.make_rectangle_rface(40, 20), (0, 0, 1), 10, end_face_tag="cap.top")
        (anchor,) = er.anchors_for_role(solid, "extrusion.end")
        filleted = scad.fillet_rsolid(solid, _edges_at(solid, 10), 2.0)

        assert _tagged(filleted, "cap.top") == 1  # the op-kwarg face channel used to stop at blends

        r = er.resolve(anchor, filleted)
        assert r.status == "ok"
        (face,) = r.entities
        assert face.get_center().z == pytest.approx(10.0)
        assert face.get_area() == pytest.approx(36 * 16)


def test_face_split_by_a_cut_is_a_split():
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        slot = scad.make_box_rsolid(4, 30, 4, (0, 0, 8))  # a groove right across the top
        cut = scad.cut_rsolid(box, slot)

        r = er.resolve(anchor, cut)
        assert r.status == "split"
        assert len(r.entities) == 2
        centers = sorted(round(face.get_center().x, 6) for face in r.entities)
        assert centers == [-11.0, 11.0]
        assert all(face.get_area() == pytest.approx(18 * 20) for face in r.entities)


# ---------------------------------------------------------------------------
# Statuses: merged, lost (deleted / no history), derived following
# ---------------------------------------------------------------------------


def test_coplanar_union_is_merged():
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        joined = scad.union_rsolid(box, scad.make_box_rsolid(20, 20, 10, (25, 0, 0)))

        r = er.resolve(anchor, joined)
        assert r.status == "merged"
        (face,) = r.entities
        assert face.get_area() == pytest.approx(1100.0)


def test_a_face_cut_away_is_lost_and_says_where():
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        cut = scad.cut_rsolid(box, scad.make_box_rsolid(50, 30, 5, (0, 0, 6)))

        r = er.resolve(anchor, cut)
        assert r.status == "lost"
        assert r.entities == []
        assert r.reason == "deleted"
        assert r.lost_at == cut.get_metadata("graph")["node_id"]


def test_a_shell_kept_face_resolves_to_itself():
    # Was the last kernel gap (a kept face had only the generated witness of its offset face); the tracker now
    # also records that it stays (owner decision, option a).
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        shelled = scad.shell_rsolid(box, _faces_at(box, 0), 1.0)

        r = er.resolve(anchor, shelled)
        assert r.status == "ok"
        (face,) = r.entities
        assert face.get_center().z == pytest.approx(10.0)
        assert face.get_area() == pytest.approx(800.0)
        # The offset face it generated is reachable in derived mode, the face itself among the targets.
        derived = er.resolve(anchor, shelled, follow="derived")
        assert sorted(round(f.get_center().z, 6) for f in derived.entities) == [9.0, 10.0]


def test_an_edge_followed_into_its_fillet_patch():
    with scad.GraphSession():
        box = scad.make_box_rsolid(40, 20, 10)
        edges = _edges_at(box, 10)
        (long_edge,) = [e for e in edges if e.get_center().y > 9 and abs(e.get_center().x) < 1e-6]
        anchor = er.anchor_of(long_edge)
        filleted = scad.fillet_rsolid(box, edges, 2.0)

        identity = er.resolve(anchor, filleted)
        assert identity.status == "lost" and identity.reason == "deleted"

        derived = er.resolve(anchor, filleted, follow="derived")
        faces = [e for e in derived.entities if type(e).__name__ == "Face"]
        assert len(faces) == 1
        # The quarter-round patch (r = 2) along the 40 mm edge, mitred into its neighbours at both ends.
        assert math.pi * 36 < faces[0].get_area() < math.pi * 40
        assert faces[0].get_center().y > 8 and faces[0].get_center().z > 8


# ---------------------------------------------------------------------------
# Stability across re-execution with other parameters
# ---------------------------------------------------------------------------


def _bracket(width: float):
    solid = scad.extrude_rsolid(scad.make_rectangle_rface(width, 20), (0, 0, 1), 10)
    (anchor,) = er.anchors_for_role(solid, "extrusion.end")
    solid = scad.cut_rsolid(solid, scad.make_cylinder_rsolid(3, 30))
    solid = scad.fillet_rsolid(solid, _edges_at(solid, 0), 1.0)
    return solid, anchor


@pytest.mark.parametrize("width", [30.0, 40.0, 55.0])
def test_a_role_anchor_resolves_the_same_face_after_a_parameter_change(width):
    with scad.GraphSession():
        solid, anchor = _bracket(width)
        r = er.resolve(anchor, solid)
        assert r.status == "ok"
        (face,) = r.entities
        assert face.get_center().z == pytest.approx(10.0)
        assert face.get_area() == pytest.approx(width * 20 - math.pi * 9, rel=1e-6)


def _creator(kind: str):
    if kind == "extrude":
        return scad.extrude_rsolid(scad.make_rectangle_rface(10, 10), (0, 0, 1), 10), "extrusion.end", (0, 0, -1)
    if kind == "revolve":
        face = scad.make_rectangle_rface(4, 4, (10, 0, 0), (0, 1, 0))
        return scad.revolve_rsolid(face, (0, 0, 1), 90), "revolution.end", (10, -0.5, -1)
    if kind == "loft":
        wires = [scad.make_rectangle_rwire(10, 10), scad.make_rectangle_rwire(6, 6, (0, 0, 10))]
        return scad.loft_rsolid(wires), "loft.end", (0, 0, -1)
    path = scad.make_wire_from_edges_rwire([scad.make_line_redge((0, 0, 0), (0, 0, 10))])
    return scad.sweep_rsolid(scad.make_circle_rface((0, 0, 0), 2), path), "sweep.end", (0, 0, -1)


@pytest.mark.parametrize("kind", ["extrude", "revolve", "loft", "sweep"])
def test_a_creator_end_cap_anchor_survives_a_boolean_and_a_copy(kind):
    with scad.GraphSession():
        solid, role, boss_at = _creator(kind)  # a boss overlapping the start, away from the end cap
        (anchor,) = er.anchors_for_role(solid, role)
        (cap,) = er.resolve(anchor, solid).entities
        area = cap.get_area()
        later = scad.union_rsolid(solid, scad.make_box_rsolid(2, 2, 2, boss_at))
        later = scad.translate_shape(later, (0, 0, 5))
        r = er.resolve(anchor, later)
        assert r.status == "ok"
        (face,) = r.entities
        assert face.get_area() == pytest.approx(area)
        assert [hop["op"] for hop in r.hops][-2:] == ["make_union_rsolid", "make_translate_rshape"]


# ---------------------------------------------------------------------------
# Audit: per operation family, the tag channels and the history today
# ---------------------------------------------------------------------------

_AUDIT = {
    # family: (op on the tagged box, plain tag survives, op-kwarg tag survives, history status).  Before tags
    # became a view over history the plain tag survived nothing and the kwarg tag only booleans and the shell.
    "cut": (lambda b: scad.cut_rsolid(b, scad.make_cylinder_rsolid(3, 30)), 1, 1, "ok"),
    "union": (lambda b: scad.union_rsolid(b, scad.make_box_rsolid(4, 4, 4, (0, 0, 10))), 1, 1, "ok"),
    "intersect": (lambda b: scad.intersect_rsolid(b, scad.make_box_rsolid(30, 30, 30, (10, 0, -5))), 1, 1, "ok"),
    "fillet": (lambda b: scad.fillet_rsolid(b, _edges_at(b, 10), 2.0), 1, 1, "ok"),
    "chamfer": (lambda b: scad.chamfer_rsolid(b, _edges_at(b, 10), 2.0), 1, 1, "ok"),
    "shell_kept_face": (lambda b: scad.shell_rsolid(b, _faces_at(b, 0), 1.0), 1, 1, "ok"),
    "shell_opened_face": (lambda b: scad.shell_rsolid(b, _faces_at(b, 10), 1.0), 1, 1, "ok"),
    "translate": (lambda b: scad.translate_shape(b, (5, 0, 0)), 1, 1, "ok"),
    "mirror": (lambda b: scad.mirror_shape(b, (0, 0, 0), (1, 0, 0)), 1, 1, "ok"),
    "linear_pattern": (lambda b: scad.linear_pattern_rsolidlist(b, (1, 0, 0), 3, 50)[2], 1, 1, "ok"),
    "rotate": (lambda b: scad.rotate_shape(b, 30, (0, 0, 1)), 1, 1, "ok"),
    "radial_pattern": (lambda b: scad.radial_pattern_rsolidlist(b, (0, 0, 0), (0, 0, 1), 4, 360)[1], 1, 1, "ok"),
    # These five recorded no history before this branch (lost / no_history); they now carry builder history.
    "scale": (lambda b: scad.scale_rsolid(b, (1.0, 1.0, 1.0)), 1, 1, "ok"),
    "transform_rsolid": (
        lambda b: scad.transform_rsolid(b, [[1, 0, 0, 5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]),
        1,
        1,
        "ok",
    ),
    "offset": (lambda b: scad.offset_rsolid(b, -1.0), 1, 1, "ok"),
}


@pytest.mark.parametrize("family", sorted(_AUDIT))
def test_audit_tag_channels_and_history_per_family(family):
    op, plain, kwarg, status = _AUDIT[family]
    with scad.GraphSession():
        box = scad.make_box_rsolid(40, 20, 10, top_face_tag="kw.top")
        (top,) = _faces_at(box, 10)
        anchor = er.anchor_of(top)
        box = scad.apply_tag_rselection(box, [top], "user.top")
        out = op(box)
        assert (_tagged(out, "user.top"), _tagged(out, "kw.top")) == (plain, kwarg)
        r = er.resolve(anchor, out)
        assert r.status == status
        if status == "lost":
            assert r.reason in {"no_history", "replaced"}
        elif family != "offset":
            # Whatever the history found, it is the top plane (or what is left of it).
            assert all(face.get_center().z == pytest.approx(10.0) for face in r.entities)


# ---------------------------------------------------------------------------
# History through the operations that had none: transform, scale, offset, draft, helical sweep
# ---------------------------------------------------------------------------

_SHEAR = [[1, 0.2, 0, 0], [0, 1, 0, 0], [0, 0, 2, 0], [0, 0, 0, 1]]


@pytest.mark.parametrize(
    "name, op, z, area",
    [
        ("transform_rigid", lambda b: scad.transform_rsolid(b, [[0, -1, 0, 5], [1, 0, 0, 0], [0, 0, 1, 3], [0, 0, 0, 1]]), 13.0, 800.0),
        ("transform_affine", lambda b: scad.transform_rsolid(b, _SHEAR), 20.0, 800.0),
        ("scale_uniform", lambda b: scad.scale_rsolid(b, (2.0, 2.0, 2.0)), 20.0, 3200.0),
        ("scale_axes", lambda b: scad.scale_rsolid(b, (1.0, 0.5, 3.0)), 30.0, 400.0),
        ("offset_out", lambda b: scad.offset_rsolid(b, 1.0), 11.0, 800.0),
        ("offset_in", lambda b: scad.offset_rsolid(b, -1.0), 9.0, 38 * 18),
        ("draft_zero", lambda b: scad.draft_rsolid(b, _x_faces(b), 0.0, (0, 0, 0), (0, 0, 1)), 10.0, 800.0),
    ],
)
def test_history_through_operations_that_had_none(name, op, z, area):
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        out = op(box)
        r = er.resolve(anchor, out)
        assert r.status == "ok", (name, r.reason)
        (face,) = r.entities
        assert face.get_center().z == pytest.approx(z)
        assert face.get_area() == pytest.approx(area)
        assert r.hops[-1]["op"] == out.get_metadata("graph")["op"]


def _x_faces(shape):
    return ql.faces().where(ql.prop("geom.normal.x", ">=", 0.9)).resolve(shape)


def test_history_through_a_draft_follows_the_drafted_face_and_its_neighbour():
    with scad.GraphSession():
        box = scad.make_box_rsolid(40, 20, 10)
        (side,) = _x_faces(box)
        (top,) = _faces_at(box, 10)
        side_anchor, top_anchor = er.anchor_of(side), er.anchor_of(top)
        drafted = scad.draft_rsolid(box, [side], 5.0, (0, 0, 0), (0, 0, 1))

        r = er.resolve(side_anchor, drafted)
        assert r.status == "ok"
        (face,) = r.entities
        n = face.get_normal_at()
        assert n.x == pytest.approx(math.cos(math.radians(5)), abs=1e-6)  # tilted by the draft angle
        r = er.resolve(top_anchor, drafted)
        assert r.status == "ok"
        assert r.entities[0].get_center().z == pytest.approx(10.0)
        assert r.entities[0].get_area() < 800.0  # trimmed by the inward draft


def test_a_helical_sweep_cap_is_anchored_by_the_sweep_it_records():
    with scad.GraphSession():
        solid = scad.helical_sweep_rsolid(scad.make_circle_rwire((10, 0, 0), 1, (0, 1, 0)), 5, 10, 10)
        (anchor,) = er.anchors_for_role(solid, "sweep.end")
        (cap,) = er.resolve(anchor, solid).entities
        later = scad.translate_shape(scad.union_rsolid(solid, scad.make_box_rsolid(4, 4, 4, (10, 0, -2))), (0, 0, 1))
        r = er.resolve(anchor, later)
        assert r.status == "ok"
        assert r.entities[0].get_area() == pytest.approx(cap.get_area())


# ---------------------------------------------------------------------------
# Stable anchors: an operation inserted earlier in the cell does not shift them
# ---------------------------------------------------------------------------


def _cell(insert: bool):
    """One notebook cell ("cellA"); *insert* adds operations before and after the box, as an edit would."""

    with scad.GraphSession(namespace="cellA"):
        if insert:
            # Inserted first: another box, so the first make_box node of the cell is now this one.
            stand = scad.make_box_rsolid(4, 4, 30, (18, 0, -10))  # pierces the plate
        box = scad.make_box_rsolid(40, 20, 10)
        if insert:
            box = scad.union_rsolid(box, stand)
            box = scad.cut_rsolid(box, scad.translate_shape(scad.make_cylinder_rsolid(1, 30), (15, 5, -5)))
        cut = scad.cut_rsolid(box, scad.make_cylinder_rsolid(3, 30))
        out = scad.fillet_rsolid(cut, ql.edges().where(_z(-1e-6, 1e-6)).resolve(cut), 0.5)
    return box, out


def test_an_operation_inserted_earlier_in_the_cell_does_not_shift_a_stable_anchor():
    box, out = _cell(insert=False)
    (top,) = _faces_at(out, 10)
    raw = er.anchor_of(_faces_at(box, 10)[0])
    stable = er.stable_anchor_of(_faces_at(box, 10)[0], out)
    assert (stable["feature"], stable["op"], stable["occurrence"], stable["role"]) == ("cellA", "make_box_rsolid", 0, "box.top")
    assert raw["node_id"] == "cellA_node_00000001"
    assert er.resolve(stable, out).entities[0].get_area() == pytest.approx(top.get_area())

    _, edited = _cell(insert=True)
    # The raw node id now names the inserted stand: its top face, the wrong face, reached through the union.
    wrong = er.resolve(raw, edited)
    assert wrong.status in {"ok", "merged"}
    assert all(face.get_center().z == pytest.approx(20.0) for face in wrong.entities)
    # The stable anchor still names the plate's top: 800 - the stand's 4x4 section - the two holes.
    right = er.resolve(stable, edited)
    assert right.status == "ok"
    (face,) = right.entities
    assert face.get_center().z == pytest.approx(10.0)
    assert face.get_area() == pytest.approx(800 - 16 - 9 * math.pi - math.pi, rel=1e-6)


# ---------------------------------------------------------------------------
# Splits are an error the person resolves; lost references offer ranked look-alikes
# ---------------------------------------------------------------------------


def test_a_split_reference_is_an_error_that_carries_the_pieces():
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        cut = scad.cut_rsolid(box, scad.make_box_rsolid(4, 30, 4, (0, 0, 8)))

        with pytest.raises(er.ElementRefError) as caught:
            er.require(anchor, cut)
        error = caught.value
        assert error.status == "split"
        assert [round(c.center[0], 6) for c in error.candidates] == [-11.0, 11.0]  # geometric order, not OCCT's
        described = error.resolved.describe()
        assert described["status"] == "split" and len(described["candidates"]) == 2
        assert {c["geom_type"] for c in described["candidates"]} == {"PLANE"}

        (chosen,) = er.require(anchor, cut, piece=1)
        assert chosen.get_center().x == pytest.approx(11.0)
        with pytest.raises(er.ElementRefError):
            er.require(anchor, cut, piece=2)


def test_a_lost_reference_is_an_error_with_look_alikes_ranked_by_its_guard():
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        guard = er.guard_of(_faces_at(box, 10)[0])
        cut = scad.cut_rsolid(box, scad.make_box_rsolid(50, 30, 5, (0, 0, 6)))  # removes the top 4 mm

        with pytest.raises(er.ElementRefError) as caught:
            er.require(anchor, cut, guard=guard)
        error = caught.value
        assert error.status == "lost" and error.resolved.reason == "deleted"
        best = error.candidates[0]
        assert best.geom_type == "PLANE"
        assert best.center[2] == pytest.approx(6.0)  # the new top: offered, never applied


def test_a_parameter_edit_keeps_the_stable_anchor():
    _, out = _cell(insert=False)
    # Picked on the finished part; the anchor is traced back to where the face was born.
    stable = er.stable_anchor_of(_faces_at(out, 10)[0], out)
    assert (stable["op"], stable["role"]) == ("make_box_rsolid", "box.top")
    with scad.GraphSession(namespace="cellA"):
        box = scad.make_box_rsolid(55, 20, 10)  # the edit: another width
        cut = scad.cut_rsolid(box, scad.make_cylinder_rsolid(3, 30))
        edited = scad.fillet_rsolid(cut, ql.edges().where(_z(-1e-6, 1e-6)).resolve(cut), 0.5)
    r = er.resolve(stable, edited)
    assert r.status == "ok"
    assert r.entities[0].get_area() == pytest.approx(55 * 20 - 9 * math.pi, rel=1e-6)


def test_two_look_alike_boxes_make_the_anchor_ambiguous_never_a_guess():
    _, out = _cell(insert=False)
    stable = er.stable_anchor_of(_faces_at(out, 10)[0], out)
    with scad.GraphSession(namespace="cellA"):
        # Inserted: a box with the plate's own parameters, moved beside it and fed into the same body.
        twin = scad.translate_shape(scad.make_box_rsolid(40, 20, 10), (40, 0, 0))
        box = scad.union_rsolid(scad.make_box_rsolid(40, 20, 10), twin)
        edited = scad.cut_rsolid(box, scad.make_cylinder_rsolid(3, 30))
    r = er.resolve(stable, edited)
    assert r.status == "lost"
    assert r.reason == "anchor_ambiguous"


# ---------------------------------------------------------------------------
# Tags as a view over history: chains, persistence
# ---------------------------------------------------------------------------


def test_an_n_ary_cut_composes_its_steps():
    # One node cuts three tools in turn; its steps name the intermediate solids, which the delta now composes
    # back to the real inputs, so the top face is followed through all three (here: split by the groove).
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        cut = scad.cut_rsolid(
            box,
            scad.make_cylinder_rsolid(3, 30),
            scad.translate_shape(scad.make_cylinder_rsolid(2, 30), (10, 0, 0)),
            scad.translate_shape(scad.make_box_rsolid(4, 30, 4, (0, 0, 8)), (-14, 0, 0)),
        )
        r = er.resolve(anchor, cut)
        assert r.status == "split"
        assert sorted(round(f.get_area(), 2) for f in r.entities) == [80.0, round(640 - 13 * math.pi, 2)]
        assert sorted(round(f.get_area(), 2) for f in ql.faces().where(ql.tag("user.top")).resolve(cut)) == [
            80.0,
            round(640 - 13 * math.pi, 2),
        ]


def test_a_tag_survives_pickling_with_its_history():
    import pickle

    with scad.GraphSession():
        box, _ = _box_with_top_anchor()
        holed = scad.cut_rsolid(box, scad.make_cylinder_rsolid(3, 30))
        cut = scad.fillet_rsolid(holed, _edges_at(holed, 0), 1.0)
        data = pickle.dumps(cut)
    restored = pickle.loads(data)
    (face,) = ql.faces().where(ql.tag("user.top")).resolve(restored)
    assert face.get_area() == pytest.approx(800 - 9 * math.pi)
    explained = scad.explain_tag(face, "user.top")
    assert explained and explained[0]["lineage"][0]["evidence"]["via"] == "recorded_history"


def test_tags_and_references_resolve_on_values_restored_from_the_cell_cache(tmp_path):
    # The cell cache writes a cell's nodes beside its entry (runtime/lineage.py) and pickles its values; a fresh
    # process registers the nodes, then unpickles the values.  The tag view and the resolver read those nodes.
    import json
    import subprocess
    import sys
    import textwrap

    root = str(tmp_path)
    build = textwrap.dedent(
        f"""
        import json, pickle, math
        from pathlib import Path
        import simplecadapi as scad
        from simplecadapi import ql
        from simplecadapi._glue.session import GraphSession
        from simplecadapi.runtime import lineage
        from simplecadapi.topology import element_ref as er
        with GraphSession(graph_id="g1", namespace="cellA", shared_lineage=True) as session:
            box = scad.make_box_rsolid(40, 20, 10)
            top = ql.faces().where(ql.prop("geom.center.z", ">=", 9.99)).exactly(1).resolve(box)
            box = scad.apply_tag_rselection(box, top, "user.top")
            out = scad.cut_rsolid(box, scad.make_cylinder_rsolid(3, 30))
            anchor = er.stable_anchor_of(top[0], out)
        lineage.save(Path({root!r}), "cellA", session)
        Path({root!r}, "value.pkl").write_bytes(pickle.dumps(out))
        Path({root!r}, "anchor.json").write_text(json.dumps(anchor))
        """
    )
    restore = textwrap.dedent(
        f"""
        import json, pickle
        from pathlib import Path
        from simplecadapi import ql
        from simplecadapi.runtime import lineage
        from simplecadapi.topology import element_ref as er
        assert lineage.load(Path({root!r}), "cellA", "g1")
        out = pickle.loads(Path({root!r}, "value.pkl").read_bytes())
        tagged = ql.faces().where(ql.tag("user.top")).resolve(out)
        r = er.resolve(json.loads(Path({root!r}, "anchor.json").read_text()), out)
        print(json.dumps({{"tagged": [f.get_area() for f in tagged], "status": r.status,
                          "areas": [f.get_area() for f in r.entities]}}))
        """
    )
    for code in (build, restore):
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, done.stderr[-1500:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["status"] == "ok"
    assert result["tagged"] == pytest.approx([800 - 9 * math.pi])
    assert result["areas"] == pytest.approx([800 - 9 * math.pi])


def test_a_reference_says_which_body_and_which_naming_version():
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        stable = er.stable_anchor_of(_faces_at(box, 10)[0], box)
        assert stable["naming"] == er.NAMING_VERSION
        # A cut that leaves two bodies is allowed (not a reference error): each body is its own output slot, and
        # the reference resolves in each body to the piece of the top face that body has.
        pieces = scad.cut_rsolid_list(box, scad.make_box_rsolid(4, 30, 30, (0, 0, -10)))
        assert len(pieces) == 2
        halves = [er.resolve(anchor, piece) for piece in pieces]
        assert [r.status for r in halves] == ["ok", "ok"]
        assert sorted(round(r.entities[0].get_center().x, 6) for r in halves) == [-11.0, 11.0]
        assert all(r.bodies == [0] for r in halves)
    # A reference made under another naming version still resolves, and says so (the caller checks its guard).
    r = er.resolve(dict(stable, naming="scad-naming/0"), box)
    assert r.status == "ok" and r.version_changed and r.bodies == [0]
