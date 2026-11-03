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

        assert _tagged(cut, "user.top") == 0  # today: the face-source gate drops the tag

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

        assert _tagged(filleted, "user.top") == 0

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

        assert _tagged(filleted, "cap.top") == 0  # today: the op-kwarg face channel stops at blends

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


def test_an_operation_without_history_loses_the_reference_instead_of_guessing():
    with scad.GraphSession():
        box, anchor = _box_with_top_anchor()
        moved = scad.transform_rsolid(box, [[1, 0, 0, 5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])

        r = er.resolve(anchor, moved)
        assert r.status == "lost"
        assert r.reason == "no_history"


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
    # family: (op on the tagged box, plain tag survives, op-kwarg tag survives, history status)
    "cut": (lambda b: scad.cut_rsolid(b, scad.make_cylinder_rsolid(3, 30)), 0, 1, "ok"),
    "union": (lambda b: scad.union_rsolid(b, scad.make_box_rsolid(4, 4, 4, (0, 0, 10))), 0, 1, "ok"),
    "intersect": (lambda b: scad.intersect_rsolid(b, scad.make_box_rsolid(30, 30, 30, (10, 0, -5))), 0, 1, "ok"),
    "fillet": (lambda b: scad.fillet_rsolid(b, _edges_at(b, 10), 2.0), 0, 0, "ok"),
    "chamfer": (lambda b: scad.chamfer_rsolid(b, _edges_at(b, 10), 2.0), 0, 0, "ok"),
    # Kept faces of a shell carry only a Generated witness (their offset face), no Preserved one.
    "shell_kept_face": (lambda b: scad.shell_rsolid(b, _faces_at(b, 0), 1.0), 0, 0, "lost"),
    "shell_opened_face": (lambda b: scad.shell_rsolid(b, _faces_at(b, 10), 1.0), 0, 1, "ok"),
    "translate": (lambda b: scad.translate_shape(b, (5, 0, 0)), 0, 0, "ok"),
    "mirror": (lambda b: scad.mirror_shape(b, (0, 0, 0), (1, 0, 0)), 0, 0, "ok"),
    "linear_pattern": (lambda b: scad.linear_pattern_rsolidlist(b, (1, 0, 0), 3, 50)[2], 0, 0, "ok"),
    "rotate": (lambda b: scad.rotate_shape(b, 30, (0, 0, 1)), 0, 0, "ok"),
    "radial_pattern": (lambda b: scad.radial_pattern_rsolidlist(b, (0, 0, 0), (0, 0, 1), 4, 360)[1], 0, 0, "ok"),
    "scale": (lambda b: scad.scale_rsolid(b, (1.0, 1.0, 1.0)), 0, 0, "lost"),
    "transform_rsolid": (
        lambda b: scad.transform_rsolid(b, [[1, 0, 0, 5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]),
        0,
        0,
        "lost",
    ),
    "offset": (lambda b: scad.offset_rsolid(b, 1.0), 0, 0, "lost"),
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
        else:
            # Whatever the history found, it is the top plane (or what is left of it).
            assert all(face.get_center().z == pytest.approx(10.0) for face in r.entities)
