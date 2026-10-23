"""Tag data model, TaggedMixin and the public tag operators, against the reference SDK.

Ids that Python draws at random (binding ids, uuid4) are replaced by fixed ones before
comparing; ids that Python derives deterministically (uuid5) are compared as they are.
"""

import json
import textwrap

import pytest
from ref import close, golden

import simplecadapi._cpp as scad
from simplecadapi._cpp import _testing, tagging

_FACTORY_SNIPPET = """
    t = scad.tagging

    def fixed(binding):
        d = binding.to_dict()
        d["binding_id"] = "tag_binding_fixed"
        return d

    user = t.TagBinding(
        tag="role.datum",
        producer=t.TagProducer("user_operation", node_id="n_7"),
        scope=t.TagBindingScope("n_3", 1),
        target=t.TagTarget("selection_query", selector={"target_kind": "face"}),
        propagation=t.TagPropagation("downward", "continuation_fragment"),
        evidence=t.TagEvidence("query_execution", {"selected_count": 2, "selected_refs": []}),
        binding_id="tag_binding_fixed",
    )
    projected = t.projected_tag_binding(
        user, operation="make_extrude_rsolid", role="extrusion.side",
        source_topo_id="edge_1", target_topo_id="face_2", evidence_method="Generated",
    )
    again = t.projected_tag_binding(
        projected, operation="make_translate_rshape", role="modified",
        source_topo_id="face_2", target_topo_id="face_9", evidence_method="Modified",
        topology="downward",
    )
    explicit = t.TagPropagation("local", "explicit", ("merge", "intersection"))
    derivations = [d.value for d in t.LineageDerivation]
    policies = [p.value for p in t.LineagePolicy if p.value != "explicit"]
    result = {
        "user": fixed(user),
        "role": t.operation_role_tag_binding(
            "face.box.top", operation="make_box_rsolid", role="box.top",
            target_topo_id="face_3", evidence_method="Generated").to_dict(),
        "projected": projected.to_dict(),
        "projected_twice": again.to_dict(),
        "user_default": fixed(t.user_tag_binding("role.mount", node_id="n_1")),
        "internal": fixed(t.internal_tag_binding("face.top", topology="downward", evidence={"extra": 1})),
        "legacy": fixed(t.legacy_tag_binding("legacy.thing", diagnostic="old")),
        "allows": {p: {d: t.lineage_policy_allows(p, d) for d in derivations} for p in policies},
        "allows_explicit": {d: t.lineage_policy_allows(explicit, d) for d in derivations},
        "normalized": [t.normalize_tag(x, strict=False) for x in ["Hello World:x/y", " Face.Top ", "a  b"]],
        "is_normalized": [t.is_normalized_tag(x) for x in ["face.top", "Face.top", "a..b", "a.1b", "a-b_c.d9", ""]],
        "anchors": {x: t.resolve_anchor_tag_candidates(x)
                    for x in ["mounting_surface", "role.datum", "face.top", "anchor.pin", "legacy.old", "custom.thing", "  "]},
        "policy": {x: t.DEFAULT_TAG_POLICY.should_propagate(x)
                   for x in ["role.mount", "face.top", "top", "anchor.a", "group.g", "solid.x", "misc"]},
        "roundtrip_equal": t.TagBinding.from_dict(user.to_dict()) == user,
    }
"""


def _run_cpp(snippet):
    """Run a reference snippet against this module (shapes come from the test helpers)."""
    code = textwrap.dedent(snippet).replace("scad.make_box_rsolid(", "scad._testing.box(")
    namespace = {"scad": scad, "result": None}
    exec(code, namespace)
    return json.loads(json.dumps(namespace["result"], default=float))


def test_binding_factories_and_rules_match_the_reference():
    expected = golden("semantic_tag_factories", _FACTORY_SNIPPET)
    actual = _run_cpp(_FACTORY_SNIPPET)
    assert actual.keys() == expected.keys()
    for key in expected:
        assert close(actual[key], expected[key]), key


_EXPLAIN_SNIPPET = """
    box = scad.make_box_rsolid(1.0, 1.0, 1.0)
    box._apply_user_tag("role.x", topology_propagation="downward")
    face = box.get_faces(0)
    edge = face.get_edges(0)
    own = box._explain_tag("role.x", "local")[0]
    on_face = face._explain_tag("role.x")[0]
    on_edge = edge._explain_tag("role.x")[0]
    result = {
        "own_keys": list(own.keys()),
        "own_binding_keys": list(own["binding"].keys()),
        "own_attachment": own["attachment"],
        "face_keys": list(on_face.keys()),
        "face_attachment": on_face["attachment"],
        "face_scope": on_face["scope"],
        "face_path_len": len(on_face["topology_path"]),
        "face_path_root": on_face["topology_path"][0] == box.topo_id,
        "face_path_leaf": on_face["topology_path"][-1] == face.topo_id,
        "edge_path_len": len(on_edge["topology_path"]),
        "face_local": face._list_tags("local"),
        "face_inherited": face._list_tags("inherited"),
        "effective_has": "role.x" in edge._list_tags(),
    }
"""


def test_explanations_have_the_reference_layout():
    expected = golden("semantic_tag_explain_layout", _EXPLAIN_SNIPPET)
    actual = _run_cpp(_EXPLAIN_SNIPPET)
    # The kernel-applied names (face.*, wire.*, edge.*) come from construction order, which differs.
    for side in (expected, actual):
        side["face_local"] = [t for t in side["face_local"] if not t.startswith(("face.", "wire.", "edge."))]
    assert actual == expected


def test_enums_are_str_enums_and_accept_strings():
    assert scad.TagScope.LOCAL == "local"
    assert isinstance(scad.TagScope.LOCAL, str)
    assert scad.TopologyPropagation.DOWNWARD.value == "downward"
    assert [m.name for m in scad.LineagePolicy] == ["NONE", "CONTINUATION", "CONTINUATION_FRAGMENT", "EXPLICIT"]
    box = _testing.box(1, 1, 1)
    scad.apply_tag(box, "role.a")
    assert scad.list_tags(box, "local") == scad.list_tags(box, scad.TagScope.LOCAL) == ["role.a"]
    assert scad.list_tags(box, " LOCAL ") == ["role.a"]
    with pytest.raises(ValueError, match="unsupported tag scope 'bogus'; expected one of: effective, inherited, lineage, local"):
        scad.list_tags(box, "bogus")
    binding = tagging.TagBinding(tag="x.y", producer=tagging.TagProducer("user_operation"))
    assert binding.propagation.lineage is scad.LineagePolicy.CONTINUATION_FRAGMENT
    assert binding.producer.kind == "user_operation"
    with pytest.raises(scad.SimpleCADError, match="unsupported producer kind 'nobody'"):
        tagging.TagProducer("nobody")


def test_records_validate_like_the_dataclasses():
    with pytest.raises(scad.SimpleCADError) as info:
        tagging.TagProducer("auto_rule")
    assert info.value.to_dict()["what_happened"] == "auto_rule producers require rule_id and rule_version"
    with pytest.raises(scad.SimpleCADError) as info:
        tagging.TagBinding(tag="Bad", producer=tagging.TagProducer("user_operation"))
    assert "not normalized" in info.value.to_dict()["what_happened"]
    with pytest.raises(scad.SimpleCADError) as info:
        tagging.TagEvidence("user_assertion", {"kind": "x"})
    assert info.value.to_dict()["what_happened"] == "evidence data cannot redefine kind"
    with pytest.raises(scad.SimpleCADError) as info:
        tagging.TagTarget("explicit_refs")
    assert info.value.to_dict()["what_happened"] == "explicit_refs targets require refs"
    payload = tagging.user_tag_binding("role.a").to_dict()
    with pytest.raises(scad.SimpleCADError) as info:
        tagging.TagBinding.from_dict({**payload, "unknown": True})
    assert info.value.to_dict()["what_happened"] == "TagBinding contains unknown field(s): unknown"
    assert tagging.TagBinding.from_dict(payload).to_dict() == payload


def test_downward_propagation_is_computed_not_copied():
    box = _testing.box(1, 1, 1)
    binding = box._apply_user_tag("role.mounting_surface", topology_propagation="downward")
    face = box.get_faces(0)
    edge = face.get_edges(0)
    assert "role.mounting_surface" not in face._list_tags("local")
    assert "role.mounting_surface" in face._list_tags("inherited")
    assert "role.mounting_surface" in edge._list_tags("inherited")
    assert binding not in face._tag_bindings
    assert "role.mounting_surface" in face._tags


def test_apply_tag_does_not_infer_propagation_from_prefix():
    box = _testing.box(1, 1, 1)
    returned = scad.apply_tag(box, "role.mounting_surface")
    assert returned is box
    assert "role.mounting_surface" in box._list_tags("local")
    assert not any("role.mounting_surface" in f._list_tags("effective") for f in box.faces())


def test_lineage_scope_needs_complete_history():
    source, result = _testing.box(1, 1, 1), _testing.box(2, 2, 2)
    binding = source._apply_user_tag("role.datum")
    with pytest.raises(scad.SimpleCADError, match="lineage tag scope requires complete topology history; coverage=none"):
        result._list_tags("lineage")
    result._add_tag_lineage(binding, derivation="continuation", source_topo_id=source.topo_id,
                            evidence=tagging.TagEvidence("topology_change", {"change_ids": ["c1"]}))
    result._set_runtime("semantic.lineage.coverage", "complete")
    assert "role.datum" not in result._list_tags("effective")
    assert result._list_tags("lineage") == ["role.datum"]
    explained = scad.explain_tag(result, "role.datum", "lineage")
    assert explained[0]["lineage"][0]["derivation"] == "continuation"


def test_same_token_from_two_producers_explains_both():
    box = _testing.box(1, 1, 1)
    box._add_tag_binding(tagging.user_tag_binding("role.datum", node_id="node_user"))
    box._add_tag_binding(tagging.TagBinding(
        tag="role.datum",
        producer=tagging.TagProducer("auto_rule", rule_id="simplecad.test.datum", rule_version="1.0"),
        evidence=tagging.TagEvidence("geometry_classification"),
        certainty="proven", lifecycle="recompute"))
    assert box._list_tags("local") == ["role.datum"]
    assert {e["producer"]["kind"] for e in box._explain_tag("role.datum", "local")} == {"user_operation", "auto_rule"}
    assert box._remove_tag("role.datum") == 1
    assert box._explain_tag("role.datum", "local")[0]["producer"]["kind"] == "auto_rule"


def test_legacy_flat_tags_only_support_effective_scope():
    box = _testing.box(1, 1, 1)
    box._tags = {"legacy.marker"}
    legacy = box._explain_tag("legacy.marker", "effective")[0]
    assert legacy["producer"]["kind"] == "legacy_import"
    assert legacy["attachment"] == "effective_legacy"
    with pytest.raises(scad.SimpleCADError, match="legacy effective tag snapshots only support effective scope"):
        box._list_tags("local")


def test_apply_tag_rselection_returns_an_independent_view():
    box = _testing.box(1, 1, 1)
    source_face = box.get_faces(0)
    tagged = scad.apply_tag_rselection(box, [source_face], "role.mounting_surface",
                                       topology_propagation=scad.TopologyPropagation.LOCAL,
                                       lineage_policy=scad.LineagePolicy.CONTINUATION_FRAGMENT)
    assert tagged is not box and type(tagged) is type(box)
    assert "role.mounting_surface" not in box.get_faces(0)._list_tags("local")
    tagged_face = next(f for f in tagged.faces() if f.topo_id == source_face.topo_id)
    explanation = scad.explain_tag(tagged_face, "role.mounting_surface", scad.TagScope.LOCAL)
    assert len(explanation) == 1 and explanation[0]["producer"]["kind"] == "user_operation"
    assert explanation[0]["binding"]["target"]["kind"] == "explicit_refs"


def test_tag_operators_report_under_their_python_names():
    box = _testing.box(1, 1, 1)
    with pytest.raises(scad.SimpleCADError) as info:
        scad.apply_tag(box, "Not Normal")
    assert info.value.operation == "apply_tag"
    with pytest.raises(scad.SimpleCADError) as info:
        scad.apply_tag_rselection(box, [], "role.a")
    assert info.value.operation == "apply_tag_rselection"
    with pytest.raises(scad.SimpleCADError) as info:
        scad.apply_tag_rselection(box, "faces", "role.a")
    assert info.value.operation == "apply_tag_rselection"
    with pytest.raises(scad.SimpleCADError) as info:
        scad.select_faces_by_tag(box, "Bad Tag")
    assert info.value.operation == "select_faces_by_tag"
    with pytest.raises(scad.SimpleCADError) as info:
        scad.select_edges_by_tag(box.get_faces(0).get_edges(0), "edge.boundary")
    assert info.value.operation == "select_edges_by_tag"


def test_select_by_tag_and_auto_tags():
    box = _testing.box(2, 3, 4)
    box.auto_tag_faces("box")
    assert len(scad.select_faces_by_tag(box, "face.top")) == 1
    assert len(scad.select_edges_by_tag(box, "edge.boundary")) == 12
    assert scad.list_tags(box.get_faces(0), scad.TagScope.LOCAL) == sorted(scad.list_tags(box.get_faces(0), scad.TagScope.LOCAL))
