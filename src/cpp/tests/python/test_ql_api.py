"""The QL module through Python: ports of the reference test_ql.py / test_graph_ql.py assertions.

Shapes come from `simplecadapi._cpp._testing` (origin-corner box, cylinder) and
`simplecadapi._cpp.ql._testing` (placed boxes, cuts); the real operators land in other areas.
"""

from __future__ import annotations

import pytest

import simplecadapi._cpp as scad
from simplecadapi._cpp import _testing, ql as Q
from simplecadapi._cpp.ql import _testing as raw


def box(w, d, h, at=(0, 0, 0)):
    return raw.box_at(at, w, d, h)


def cyl(r, h, at=(0, 0, 0)):
    return raw.cylinder_at(at, r, h)


def centers(shapes):
    return [tuple(round(c, 6) for c in s.get_center()) for s in shapes]


# --------------------------------------------------------------------------------------------- module surface
def test_module_is_importable_both_ways():
    import simplecadapi._cpp.ql as imported

    assert imported is Q is scad.ql
    from simplecadapi._cpp.ql import edges, faces, tag  # noqa: F401

    for name in (
        "edges faces wires vertices solids shells tag meta value key geo center_axis prop curve_type surface_type "
        "and_ or_ not_ operation_event origin_role output_role source_binding source_topology op origin role select "
        "selector_from_dict register_property_resolver unregister_property_resolver Query ShapeSelector "
        "SerializablePredicate SerializableKey TraversalSpec MISSING"
    ).split():
        assert hasattr(Q, name), name


# --------------------------------------------------------------------------------------------- TestQLTagPredicates
def test_solid_world_bounds_distinguish_equal_volume_components():
    first = box(2, 2, 2, at=(2, -1, 4))
    second = box(2, 2, 2, at=(7, -1, 4))
    selector = Q.solids().where(
        Q.and_(Q.prop("geom.bbox.min.x", "==", 7), Q.prop("geom.bbox.max.z", "==", 6))
    ).exactly(1)
    result = selector.resolve([first, second])
    assert len(result) == 1
    assert centers(result) == centers([second])


def test_tag_exact_and_wildcard():
    b = _testing.box(1.0, 1.0, 1.0)
    b._apply_tag("role.mounting_surface", False)

    assert Q.tag("role.mounting_surface")(b)
    assert Q.tag("role.*")(b)
    assert not Q.tag("role.other")(b)


def test_tag_face_prefix():
    b = _testing.box(1.0, 1.0, 1.0)
    b.auto_tag_faces("box")
    top_faces = [f for f in Q.faces().resolve(b) if "face.top" in f._list_tags()]
    assert top_faces

    assert Q.tag("face.top")(top_faces[0])
    assert Q.tag("face.*")(top_faces[0])


def test_tag_scope_serializes_and_roundtrips():
    predicate = Q.tag("role.mounting_surface", scope="inherited")
    payload = predicate.to_dict()
    restored = Q.SerializablePredicate.from_dict(payload)

    assert payload["kind"] == "tag"
    assert payload["data"]["scope"] == "inherited"
    assert restored.to_dict() == payload
    assert restored == predicate


def test_tag_scope_evaluates_explicit_downward_inheritance():
    b = _testing.box(1.0, 1.0, 1.0)
    b._apply_tag("role.body", True)
    face = Q.faces().resolve(b)[0]

    assert not Q.tag("role.body", scope="local")(face)
    assert Q.tag("role.body", scope="inherited")(face)
    assert Q.tag("role.body", scope="effective")(face)


def test_tag_argument_validation():
    with pytest.raises(TypeError, match="pattern must be a string"):
        Q.tag(3)
    with pytest.raises(ValueError, match="pattern must be non-empty"):
        Q.tag("  ")
    with pytest.raises(ValueError, match="only trailing"):
        Q.tag("a*b")
    with pytest.raises(ValueError):
        Q.tag("a", scope="sideways")


# --------------------------------------------------------------------------------------------- TestQLMetadataPredicates
def with_geo(shape, **geo):
    shape.set_metadata("geo", dict(geo))
    return shape


def test_meta_eq_and_compare():
    b = with_geo(_testing.box(2.0, 3.0, 4.0), type="box", size={"x": 2.0})

    assert Q.meta("geo.type", "==", "box")(b)
    assert Q.meta("geo.size.x", ">", 1.0)(b)
    assert not Q.meta("geo.size.x", ">", "text")(b)


def test_meta_missing_value_is_none():
    b = _testing.box(1.0, 1.0, 1.0)
    assert Q.meta("geo.nothing", "==", None)(b)
    assert Q.meta("geo.nothing", "!=", 1)(b)
    assert not Q.meta("geo.nothing", ">", 1)(b)
    with pytest.raises(TypeError, match="op must be a string"):
        Q.meta("a", 1, 2)


def test_select_where_order_first():
    cylinders = [with_geo(_testing.cylinder(1.0, h), height=h) for h in (1.0, 3.0, 2.0)]

    result = Q.select(cylinders).order_by(Q.value("geo.height"), desc=True).first()

    assert result is not None
    assert result.get_metadata("geo")["height"] == 3.0


def test_where_and_not():
    b = with_geo(_testing.box(1.0, 1.0, 1.0), type="box")
    c = with_geo(_testing.cylinder(1.0, 1.0), type="cylinder")
    b._apply_tag("role.mounting_surface", False)
    b._apply_tag("state.debug", False)

    predicate = Q.and_(Q.meta("geo.type", "==", "box"), Q.tag("role.mounting_surface"), Q.not_(Q.tag("state.*")))
    assert Q.select([b, c]).where(predicate).all() == []

    predicate = Q.and_(Q.meta("geo.type", "==", "box"), Q.tag("role.mounting_surface"))
    assert Q.select([b, c]).where(predicate).all() == [b]


def test_combinators_accept_plain_callables():
    b = _testing.box(1.0, 1.0, 1.0)
    always = Q.and_(lambda obj: True, Q.tag("*"))
    assert callable(always) and not isinstance(always, Q.SerializablePredicate)
    assert Q.not_(lambda obj: False)(b)
    assert Q.or_(lambda obj: False, lambda obj: True)(b)
    assert isinstance(Q.or_(Q.tag("a"), Q.tag("b")), Q.SerializablePredicate)


def test_first_empty():
    assert Q.select([]).first() is None


def test_select_limit_and_all():
    items = [1, 2, 3, 4]
    assert Q.select(items).limit(2).all() == [1, 2]
    assert Q.select(items).limit(0).all() == []
    assert Q.select(items).where(lambda v: v % 2 == 0).all() == [2, 4]
    assert Q.select([3, None, 1]).order_by(lambda v: v).all() == [1, 3, None]


# --------------------------------------------------------------------------------------------- geometry selectors
def test_generic_property_predicate_matches_geometry_type():
    b = _testing.cylinder(1.0, 5.0)
    circles = [e for e in Q.edges().resolve(b) if Q.prop("geom.type", "==", "CIRCLE")(e)]
    assert len(circles) == 2


def test_generic_property_key_reads_center_axis():
    face = Q.faces().where(Q.prop("geom.normal.z", ">", 0.9)).exactly(1).resolve(box(2.0, 2.0, 3.0))[0]
    assert Q.key("geom.center.z")(face) == pytest.approx(3.0, abs=1e-6)


def test_custom_property_resolver_extends_ql_without_core_changes():
    face = Q.faces().resolve(_testing.box(1, 1, 1))[0]

    def resolver(target, path):
        if path == "custom.answer":
            return 42
        return Q.MISSING

    Q.register_property_resolver("custom.", resolver)
    try:
        assert Q.prop("custom.answer", "==", 42)(face)
        assert Q.key("custom.answer")(face) == 42
        assert not Q.prop("custom.other", "==", 42)(face)
    finally:
        Q.unregister_property_resolver("custom.")
    assert not Q.prop("custom.answer", "==", 42)(face)
    with pytest.raises(ValueError, match="prefix must be a non-empty string"):
        Q.register_property_resolver("", resolver)


def test_edge_selector_serializes_and_roundtrips():
    selector = (
        Q.edges().where(Q.prop("geom.type", "==", "CIRCLE")).order_by(Q.key("geom.center.z")).take(1).exactly(1)
    )

    payload = selector.to_dict()
    restored = Q.selector_from_dict(payload)

    assert payload["target_kind"] == "edge"
    assert payload["limit"] == 1
    assert payload["cardinality"]["exactly"] == 1
    assert restored.to_dict() == payload
    assert restored == selector


def test_selector_supports_graph_source_multi_key_and_range_cardinality():
    selector = (
        Q.faces()
        .from_source("node_a", 0)
        .order_by(Q.key("geom.center.z"), desc=True)
        .order_by(Q.key("geom.center.x"))
        .at_least(1)
        .at_most(6)
    )

    payload = selector.to_dict()
    restored = Q.selector_from_dict(payload)

    assert payload["source_node_id"] == "node_a"
    assert payload["source_output_slot"] == 0
    assert len(payload["order_keys"]) == 2
    assert payload["cardinality"]["at_least"] == 1
    assert payload["cardinality"]["at_most"] == 6
    assert restored.to_dict() == payload
    assert selector.source_node_id == "node_a" and selector.source_output_slot == 0


def test_wire_selector_reads_loop_role_property():
    face = Q.faces().resolve(_testing.box(2.0, 2.0, 2.0))[0]

    wires = Q.wires().where(Q.prop("topo.loop_role", "==", "outer")).take(1).exactly(1).resolve(face)

    assert len(wires) == 1
    assert Q.prop("topo.loop_role", "==", "outer")(wires[0])


def test_face_selector_resolves_geometry_predicates():
    selector = (
        Q.faces()
        .where(Q.prop("geom.type", "==", "PLANE"))
        .order_by(Q.key("geom.center.z"), desc=True)
        .take(1)
        .exactly(1)
    )

    faces = selector.resolve(_testing.box(2.0, 3.0, 4.0))
    assert len(faces) == 1
    assert faces[0].get_normal_at().z > 0.9


def test_edge_selector_resolves_circular_bottom_edge():
    rod = _testing.cylinder(1.0, 5.0)
    selector = (
        Q.edges().where(Q.prop("geom.type", "==", "CIRCLE")).order_by(Q.key("geom.center.z")).take(1).exactly(1)
    )

    edges = selector.resolve(rod)
    assert len(edges) == 1
    assert isinstance(edges[0], scad.Edge)
    assert edges[0].get_center().z == pytest.approx(0.0, abs=1e-9)


def test_boundary_traversal_selects_top_face_outer_edges():
    b = _testing.box(2.0, 3.0, 4.0)
    selector = (
        Q.faces()
        .where(Q.prop("geom.normal.z", ">", 0.9))
        .order_by(Q.key("geom.center.z"), desc=True)
        .take(1)
        .exactly(1)
        .boundary("wire")
        .where(Q.prop("topo.loop_role", "==", "outer"))
        .take(1)
        .exactly(1)
        .boundary("edge")
        .exactly(4)
    )

    assert len(selector.resolve(b)) == 4

    payload = selector.to_dict()
    restored = Q.selector_from_dict(payload)
    assert len(restored.resolve(b)) == 4
    assert payload["traversal"]["relation"] == "boundary"
    assert payload["source"]["traversal"]["relation"] == "boundary"


def test_boundary_traversal_selects_cut_top_edges():
    base = cyl(1.5, 4.0, at=(0.0, 0.0, -2.0))
    tool = box(4.0, 4.0, 4.0, at=(-2.0, -2.0, 0.25))
    result = raw.cut(base, tool)

    selector = (
        Q.faces()
        .where(Q.prop("geom.type", "==", "PLANE"))
        .where(Q.prop("geom.normal.z", ">", 0.9))
        .order_by(Q.key("geom.center.z"), desc=True)
        .take(1)
        .exactly(1)
        .boundary("wire")
        .where(Q.prop("topo.loop_role", "==", "outer"))
        .take(1)
        .exactly(1)
        .boundary("edge")
    )

    assert len(selector.resolve(result)) > 0


def tagged_box(w, d, h):
    b = _testing.box(w, d, h)
    b.auto_tag_faces("box")
    return b


def test_incident_face_query_selects_one_named_edge():
    solid = tagged_box(4.0, 2.0, 3.0)
    selector = (
        Q.faces()
        .where(Q.tag("face.top"))
        .boundary("edge")
        .incident_to(
            Q.faces().where(Q.tag("face.top")),
            Q.faces().where(Q.tag("face.front")),
            distinct=True,
        )
        .incident_face_count(exactly=2)
        .exactly(1)
    )

    assert len(selector.resolve(solid)) == 1
    restored = Q.selector_from_dict(selector.to_dict())
    assert len(restored.resolve(solid)) == 1
    assert selector.incident_faces_distinct and len(selector.incident_face_selectors) == 2
    assert selector.incident_face_cardinality == {"exactly": 2}


def test_shared_boundary_intersection_uses_topology_identity():
    solid = _testing.cylinder(2.0, 3.0)
    solid.auto_tag_faces("cylinder")
    start = Q.faces().where(Q.tag("face.bottom"))
    side = Q.faces().where(Q.tag("face.side"))
    shared = start.shared_boundary(side).exactly(1)
    assert len(shared.resolve(solid)) == 1
    assert len(Q.selector_from_dict(shared.to_dict()).resolve(solid)) == 1

    first = _testing.cylinder(2.0, 3.0)
    second = _testing.cylinder(2.0, 3.0)
    first._apply_tag("first.solid", False)
    second._apply_tag("second.solid", False)
    in_first = Q.solids().where(Q.tag("first.solid"))
    assert len(in_first.shared_boundary(in_first).resolve(first)) == len(Q.edges().resolve(first))
    assert len(in_first.shared_boundary(Q.solids().where(Q.tag("second.solid"))).resolve([first, second])) == 0


def test_selector_exactly_enforces_cardinality():
    b = _testing.box(1.0, 1.0, 1.0)
    selector = Q.faces().where(Q.prop("geom.type", "==", "PLANE")).take(2).exactly(1)
    with pytest.raises(ValueError):
        selector.resolve(b)


def test_selector_range_cardinality_enforces_bounds():
    b = _testing.box(1.0, 1.0, 1.0)

    with pytest.raises(ValueError):
        Q.faces().take(0).at_least(1).resolve(b)

    with pytest.raises(ValueError):
        Q.faces().at_most(1).resolve(b)


# --------------------------------------------------------------------------------------------- scopes and arguments
def test_resolve_returns_typed_handles():
    b = _testing.box(1, 1, 1)
    assert all(isinstance(f, scad.Face) for f in Q.faces().resolve(b))
    assert all(isinstance(e, scad.Edge) for e in Q.edges().resolve(b))
    assert all(isinstance(v, scad.Vertex) for v in Q.vertices().resolve(b))
    assert all(isinstance(s, scad.Solid) for s in Q.solids().resolve(b))
    assert all(isinstance(w, scad.Wire) for w in Q.faces().boundary("wire").resolve(b))
    assert (len(Q.faces().resolve(b)), len(Q.edges().resolve(b)), len(Q.vertices().resolve(b))) == (6, 12, 8)


def test_resolve_scope_errors():
    b = _testing.box(1, 1, 1)
    edge = Q.edges().resolve(b)[0]
    with pytest.raises(TypeError, match="cannot resolve QL selector scope for target_kind=face"):
        Q.faces().resolve(edge)
    with pytest.raises(TypeError, match="cannot resolve QL selector scope for target_kind=face"):
        Q.faces().resolve(42)
    with pytest.raises(TypeError, match="cannot resolve QL selector scope for target_kind=face"):
        Q.faces().resolve("not a shape")
    with pytest.raises(TypeError):
        Q.faces().resolve([b, "x"])
    assert Q.faces().resolve(iter([])) == []


def test_selector_argument_validation_messages():
    with pytest.raises(TypeError, match="only supports serializable QL predicates"):
        Q.faces().where(lambda f: True)
    with pytest.raises(TypeError, match="only supports serializable QL keys"):
        Q.faces().order_by(lambda f: 1)
    with pytest.raises(ValueError, match="count must be >= 0"):
        Q.faces().take(-1)
    with pytest.raises(ValueError, match="node_id must be a non-empty string"):
        Q.faces().from_source("")
    with pytest.raises(ValueError, match="unsupported traversal relation: adjacent"):
        Q.faces().traverse("adjacent", "edge")
    with pytest.raises(ValueError, match="unsupported traversal target kind: shell"):
        Q.faces().boundary("shell")
    with pytest.raises(TypeError, match="intersection requires another ShapeSelector"):
        Q.faces().intersection(3)
    with pytest.raises(ValueError, match="intersection operands must select the same topology kind"):
        Q.faces().intersection(Q.edges())
    with pytest.raises(ValueError, match="incident_to is only valid on an Edge selector"):
        Q.faces().incident_to(Q.faces())
    with pytest.raises(TypeError, match="incident_to requires one or more Face selectors"):
        Q.edges().incident_to()
    with pytest.raises(TypeError, match="incident_to requires one or more Face selectors"):
        Q.edges().incident_to(Q.edges())
    with pytest.raises(ValueError, match="incident_face_count is only valid on an Edge selector"):
        Q.faces().incident_face_count(exactly=1)


def test_selector_and_predicate_payload_errors():
    with pytest.raises(ValueError, match="unsupported predicate kind: bogus"):
        Q.SerializablePredicate.from_dict({"kind": "bogus"})
    with pytest.raises(ValueError, match="predicate 'tag' is missing required data: pattern"):
        Q.SerializablePredicate.from_dict({"kind": "tag", "data": {}})
    with pytest.raises(ValueError, match="predicate payload contains unknown fields"):
        Q.SerializablePredicate.from_dict({"kind": "tag", "extra": 1})
    with pytest.raises(ValueError, match="selector set_operation must be an object"):
        Q.selector_from_dict({"target_kind": "face", "set_operation": 3})
    with pytest.raises(KeyError):
        Q.selector_from_dict({})


def test_predicate_object_surface():
    p = Q.and_(Q.tag("a"), Q.prop("geom.area", ">", 1))
    assert p.kind == "and"
    assert [c.kind for c in p.children] == ["tag", "property_compare"]
    assert p.children[0].data == {"pattern": "a", "scope": "effective"}
    assert Q.SerializablePredicate("tag", {"pattern": "a"}).to_dict()["data"] == {"pattern": "a"}
    assert "SerializablePredicate(kind='and'" in repr(p)
    assert Q.curve_type("circle").to_dict()["data"] == {"path": "geom.type", "op": "==", "value": "CIRCLE"}
    assert Q.role("section").to_dict()["data"]["pattern"] == "role.section.*"
    assert Q.output_role("A.B").to_dict()["data"] == {"role": "a.b"}


def test_key_object_surface():
    assert Q.center_axis("Z").to_dict() == {"kind": "property", "data": {"path": "geom.center.z", "default": None}}
    assert Q.geo("area", 0.0).to_dict()["data"] == {"path": "geo.area", "default": 0.0}
    with pytest.raises(ValueError, match="axis must be one of"):
        Q.center_axis("w")
    assert Q.SerializableKey.from_dict(Q.value("a.b", 3).to_dict()) == Q.value("a.b", 3)


# --------------------------------------------------------------------------------------------- QL sugar (tracking)
def faces_with_track(**track):
    face = Q.faces().resolve(_testing.box(1, 1, 1))[0]
    face.set_metadata("track", track)
    return face


def test_op_predicate():
    assert Q.op("cut", "generated")(faces_with_track(op="make_cut_rsolid", event="generated"))


def test_op_predicate_wildcard():
    assert Q.op("cut")(faces_with_track(op="make_cut_rsolid", events=["modified"]))


def test_op_predicate_matches_generic_operation_alias():
    face = faces_with_track(op="make_translate_rsolid", operation="translate", event="modified")
    assert Q.op("translate", "modified")(face)
    assert Q.op("make_translate_rsolid", "modified")(face)


def test_origin_predicate():
    assert Q.origin("tool")(faces_with_track(origin_roles=["body", "tool"]))
    assert not Q.origin("tool")(faces_with_track(origin_role="body"))


def test_op_and_origin_do_not_fall_back_to_flat_tags():
    face = Q.faces().resolve(_testing.box(1, 1, 1))[0]
    face._add_tag("op.cut.generated")
    face._add_tag("origin.tool")
    assert not Q.op("cut", "generated")(face)
    assert not Q.origin("tool")(face)


def test_typed_tracking_predicates_roundtrip():
    operation = Q.operation_event("cut", "modified")
    origin = Q.origin_role("tool")
    assert Q.SerializablePredicate.from_dict(operation.to_dict()).to_dict() == operation.to_dict()
    assert Q.SerializablePredicate.from_dict(origin.to_dict()).to_dict() == origin.to_dict()
    with pytest.raises(ValueError, match="op_name must be a non-empty string"):
        Q.operation_event(" ")


def test_role_predicate():
    face = Q.faces().resolve(_testing.box(1, 1, 1))[0]
    face._add_tag("role.section.face")
    assert Q.role("section")(face)
    assert not Q.role("other")(face)
