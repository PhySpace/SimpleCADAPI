// TaggedMixin and the tag data model (core.py / topology/tagging.py; test_tagging_refactor.py).
#include "doctest.h"

#include <algorithm>
#include <set>

#include "scad/core/error.hpp"
#include "scad/semantic/selection.hpp"
#include "scad/topo/tag_factories.hpp"
#include "test_tracking_support.hpp"

using namespace scad;
using scad::tracking_test::box_solid;

namespace {

bool contains(const std::vector<std::string>& list, std::string_view item) {
  return std::find(list.begin(), list.end(), item) != list.end();
}

TagEvidence topology_change(std::string_view change_id = "change_1") {
  TagEvidence e;
  e.kind = TagEvidenceKind::TopologyChange;
  e.data.set("change_ids", Value(Value::Array{Value(std::string(change_id))}));
  return e;
}

}  // namespace

TEST_CASE("uuid5 and the deterministic bindings reproduce Python's ids") {
  CHECK(uuid5_url_hex("x") == "4cd605e7afa25360b5b9c5e9fb5c76f4");
  const TagBinding role = operation_role_tag_binding("face.box.top", "make_box_rsolid", "box.top", "face_3", "Generated");
  CHECK(role.binding_id == "tag_binding_87d1b369bb7b59a9aa02f73c288c88d2");
  CHECK(role.to_value().dump() ==
        R"({"schema_version":"1.0","binding_id":"tag_binding_87d1b369bb7b59a9aa02f73c288c88d2","tag":"face.box.top",)"
        R"("producer":{"kind":"auto_rule","node_id":null,"rule_id":"simplecad.operation_output_role","rule_version":"1.0"},)"
        R"("scope":{"node_id":null,"output_slot":0},"target":{"kind":"scope_root"},"attachment":"local",)"
        R"("propagation":{"topology":"local","lineage":"continuation_fragment"},)"
        R"("evidence":{"kind":"topology_change","operation":"make_box_rsolid","result_role":"box.top",)"
        R"("target_topo_id":"face_3","evidence_method":"Generated"},"certainty":"proven","lifecycle":"recompute"})");
}

TEST_CASE("the other factories have Python's layout") {
  CHECK(user_tag_binding("role.mount").to_value().dump().find(R"("evidence":{"kind":"user_assertion","authoring_source":"simplecadapi.apply_tag"})") !=
        std::string::npos);
  const TagBinding internal = internal_tag_binding("face.top");
  CHECK(internal.propagation().lineage == LineagePolicy::None);
  CHECK(internal.evidence->to_value().dump() == R"({"kind":"legacy_snapshot","source":"internal_annotation"})");
  const TagBinding legacy = legacy_tag_binding("x.y");
  CHECK(legacy.attachment == TagAttachment::EffectiveLegacy);
  CHECK(legacy.target().kind == TagTargetKind::LegacyEffective);
  CHECK(legacy.evidence->to_value().dump() == R"({"kind":"legacy_snapshot","imported_tags":["x.y"]})");
  CHECK_THROWS_AS((void)user_tag_binding("Not Normalized"), ValueError);
}

TEST_CASE("projected bindings are deterministic and remember the root of the chain") {
  const TagBinding source = user_tag_binding("role.datum");
  const TagBinding first = projected_tag_binding(source, "make_extrude_rsolid", "extrusion.side", "edge_1", "face_2", "Generated");
  const TagBinding again = projected_tag_binding(source, "make_extrude_rsolid", "extrusion.side", "edge_1", "face_2", "Generated");
  CHECK(first.binding_id == again.binding_id);
  CHECK(first.evidence->data.find("source_binding_id")->as_string() == source.binding_id);
  const TagBinding second = projected_tag_binding(first, "make_translate_rshape", "modified", "face_2", "face_9", "Modified");
  CHECK(second.evidence->data.find("source_binding_id")->as_string() == source.binding_id);
  CHECK(second.evidence->data.find("source_topo_id")->as_string() == "edge_1");
}

TEST_CASE("tag names, scopes and anchor candidates") {
  CHECK(is_normalized_tag("geom.primitive.box"));
  CHECK_FALSE(is_normalized_tag("Face.Top"));
  CHECK_FALSE(is_normalized_tag("size: 2x3x4"));
  const auto candidates = resolve_anchor_tag_candidates("mounting_surface");
  CHECK(candidates.front() == "role.mounting_surface");
  CHECK(candidates[1] == "anchor.mounting_surface");
  CHECK(contains(candidates, "face.mounting_surface"));
  CHECK(candidates.back() == "mounting_surface");
  CHECK(resolve_anchor_tag_candidates("face.top").front() == "role.top");
  CHECK(resolve_anchor_tag_candidates("custom.thing") == std::vector<std::string>{"custom.thing"});
  CHECK(resolve_anchor_tag_candidates("   ").empty());
  CHECK(default_tag_policy().should_propagate("role.mount"));
  CHECK_FALSE(default_tag_policy().should_propagate("face.top"));
  CHECK(default_tag_policy().should_propagate("top"));
  CHECK(lineage_policy_allows(LineagePolicy::ContinuationFragment, LineageDerivation::Fragment));
  CHECK_FALSE(lineage_policy_allows(LineagePolicy::Continuation, LineageDerivation::Fragment));
  CHECK_FALSE(lineage_policy_allows(LineagePolicy::Explicit, LineageDerivation::Merge));
  TagPropagation explicit_policy;
  explicit_policy.lineage = LineagePolicy::Explicit;
  explicit_policy.explicit_derivations = {LineageDerivation::Merge};
  CHECK(lineage_policy_allows(explicit_policy, LineageDerivation::Merge));
  CHECK_FALSE(lineage_policy_allows(explicit_policy, LineageDerivation::Boundary));
}

TEST_CASE("the wire format round-trips and is strict") {
  TagBinding binding;
  binding.binding_id = "tag_binding_mounting_surface";
  binding.tag = "role.mounting_surface";
  binding.policy.mut().producer.node_id = "node_tag";
  binding.policy.mut().scope.node_id = "node_body";
  binding.policy.mut().target.kind = TagTargetKind::SelectionQuery;
  binding.policy.mut().target.query_hash = "sha256:query";
  binding.policy.mut().target.binding_hash = "sha256:binding";
  binding.evidence.mut().kind = TagEvidenceKind::QueryExecution;
  binding.evidence.mut().data.set("selected_refs", Value::array());

  const Value payload = binding.to_value();
  CHECK(tag_binding_from_value(payload) == binding);

  Value unknown = payload;
  unknown.set("unknown", true);
  CHECK_THROWS_AS((void)tag_binding_from_value(unknown), TagValidationError);
  Value missing = payload;
  missing.erase("scope");
  try {
    (void)tag_binding_from_value(missing);
    FAIL("a binding without a scope was accepted");
  } catch (const TagValidationError& e) {
    CHECK(e.guidance().what_happened == "TagBinding is missing required field(s): scope");
  }

  TagLineageWitness witness;
  witness.binding = user_tag_binding("role.datum", UserTagOptions{.node_id = "node_source"});
  witness.derivation = LineageDerivation::Fragment;
  witness.source_topo_id = "face_source";
  witness.target_topo_id = "face_target";
  witness.evidence = topology_change();
  CHECK(tag_lineage_witness_from_value(witness.to_value()) == witness);
}

TEST_CASE("apply_tag does not infer propagation from a prefix") {
  Solid box = box_solid(1, 1, 1);
  Face face = box.faces()[0];
  box.apply_tag("role.mounting_surface");
  CHECK(box.has_tag("role.mounting_surface", TagScope::Local));
  CHECK_FALSE(face.has_tag("role.mounting_surface"));
}

TEST_CASE("downward propagation is computed from ancestors, not copied") {
  Solid box = box_solid(1, 1, 1);
  const TagBinding binding =
      user_tag_binding("role.mounting_surface", UserTagOptions{.topology = TopologyPropagation::Downward});
  box.add_binding(binding);

  const Face face = box.faces()[0];
  const Edge edge = face.edges()[0];
  const Vertex vertex = edge.vertices()[0];
  CHECK_FALSE(contains(face.list_tags(TagScope::Local), "role.mounting_surface"));
  CHECK(face.has_tag("role.mounting_surface", TagScope::Inherited));
  CHECK(edge.has_tag("role.mounting_surface", TagScope::Inherited));
  CHECK(vertex.has_tag("role.mounting_surface"));
  CHECK(face.local_tag_bindings().empty() == face.local_bindings().empty());
  for (const auto& stored : face.local_bindings()) CHECK(stored.binding_id != binding.binding_id);
  CHECK(contains(face.list_tags(), "role.mounting_surface"));

  // A sub-shape reached without enumerating its parents sees the tag as well.
  const Shape direct = box.sub(face.wrapped());
  CHECK(direct.has_tag("role.mounting_surface", TagScope::Inherited));
}

TEST_CASE("explain_tag names the inherited path from the ancestor down") {
  Solid box = box_solid(1, 1, 1);
  box.add_binding(user_tag_binding("role.mounting_surface", UserTagOptions{.topology = TopologyPropagation::Downward}));
  const Face face = box.faces()[0];
  const Edge edge = face.edges()[0];

  const auto on_face = face.explain_tag("role.mounting_surface");
  REQUIRE(on_face.size() == 1);
  CHECK(on_face[0].find("attachment")->as_string() == "inherited");
  CHECK(on_face[0].find("scope")->as_string() == "effective");
  const auto& face_path = on_face[0].find("topology_path")->as_array();
  REQUIRE(face_path.size() == 2);
  CHECK(face_path[0].as_string() == box.topo_id());
  CHECK(face_path[1].as_string() == face.topo_id());

  const auto edge_explained = edge.explain_tag("role.mounting_surface");
  REQUIRE(edge_explained.size() == 1);
  const auto& edge_path = edge_explained[0].find("topology_path")->as_array();
  CHECK(edge_path.size() == 4);  // solid, face, wire, edge
  CHECK(edge_path.front().as_string() == box.topo_id());
  CHECK(edge_path.back().as_string() == edge.topo_id());

  // Layout and key order of an explanation.
  const auto own = box.explain_tag("role.mounting_surface", TagScope::Local);
  REQUIRE(own.size() == 1);
  std::vector<std::string> keys;
  for (const auto& [key, value] : own[0].as_object()) keys.push_back(key);
  CHECK(keys == std::vector<std::string>{"scope", "binding_id", "producer", "attachment", "binding"});
  CHECK(own[0].find("attachment")->as_string() == "local");
}

TEST_CASE("effective tags exclude lineage; lineage needs complete history") {
  Solid source = box_solid(1, 1, 1);
  Solid result = box_solid(2, 2, 2);
  const TagBinding binding = user_tag_binding("role.datum");
  source.add_binding(binding);

  CHECK_THROWS_AS((void)result.list_tags(TagScope::Lineage), UnsupportedQueryCapabilityError);
  result.set_runtime("semantic.lineage.coverage", "partial");
  CHECK_THROWS_AS((void)result.list_tags(TagScope::Lineage), UnsupportedQueryCapabilityError);

  result.add_tag_lineage(binding, LineageDerivation::Continuation, source.topo_id(), topology_change());
  result.set_runtime("semantic.lineage.coverage", "complete");
  CHECK_FALSE(contains(result.list_tags(TagScope::Effective), "role.datum"));
  CHECK(result.list_tags(TagScope::Lineage) == std::vector<std::string>{"role.datum"});
  CHECK(result.has_tag("role.datum", TagScope::Lineage));
  // The same witness twice is one witness.
  result.add_tag_lineage(binding, LineageDerivation::Continuation, source.topo_id(), topology_change());
  CHECK(result.lineage_witnesses().size() == 1);

  const auto explained = result.explain_tag("role.datum", TagScope::Lineage);
  REQUIRE(explained.size() == 1);
  const auto& witnesses = explained[0].find("lineage")->as_array();
  REQUIRE(witnesses.size() == 1);
  CHECK(witnesses[0].find("derivation")->as_string() == "continuation");
  CHECK(witnesses[0].find("source_topo_id")->as_string() == source.topo_id());
}

TEST_CASE("an incomplete witness makes lineage scope unavailable") {
  Solid source = box_solid(1, 1, 1);
  Solid result = box_solid(2, 2, 2);
  const TagBinding binding = user_tag_binding("role.datum");
  result.add_tag_lineage(binding, LineageDerivation::Continuation, "face_9", topology_change(), "partial");
  result.set_runtime("semantic.lineage.coverage", "complete");
  try {
    (void)result.list_tags(TagScope::Lineage);
    FAIL("incomplete lineage was accepted");
  } catch (const UnsupportedQueryCapabilityError& e) {
    CHECK(e.guidance().what_happened == "lineage tag scope has incomplete lineage witnesses");
  }
}

TEST_CASE("the default lineage policy rejects boundary derivations") {
  Solid result = box_solid(2, 2, 2);
  const TagBinding binding = user_tag_binding("role.datum");
  result.add_tag_lineage(binding, LineageDerivation::Boundary, "face_9", topology_change());
  result.set_runtime("semantic.lineage.coverage", "complete");
  CHECK(result.list_tags(TagScope::Lineage).empty());
  CHECK(result.explain_tag("role.datum", TagScope::Lineage).empty());
}

TEST_CASE("one token from two producers is one tag but two explanations") {
  Solid vertex_owner = box_solid(1, 1, 1);
  const TagBinding user = user_tag_binding("role.datum", UserTagOptions{.node_id = "node_user"});
  TagBinding automatic;
  automatic.tag = "role.datum";
  automatic.policy.mut().producer.kind = TagProducerKind::AutoRule;
  automatic.policy.mut().producer.rule_id = "simplecad.test.datum";
  automatic.policy.mut().producer.rule_version = "1.0";
  automatic.evidence.mut().kind = TagEvidenceKind::GeometryClassification;
  automatic.certainty = TagCertainty::Proven;
  automatic.lifecycle = TagLifecycle::Recompute;
  automatic.binding_id = new_binding_id();
  vertex_owner.add_binding(user);
  vertex_owner.add_binding(automatic);

  CHECK(vertex_owner.list_tags(TagScope::Local) == std::vector<std::string>{"role.datum"});
  const auto explanations = vertex_owner.explain_tag("role.datum", TagScope::Local);
  REQUIRE(explanations.size() == 2);
  std::set<std::string> producers;
  for (const auto& e : explanations) producers.insert(e.find("producer")->find("kind")->as_string());
  CHECK(producers == std::set<std::string>{"user_operation", "auto_rule"});

  CHECK(vertex_owner.remove_tag_bindings("role.datum") == 1);  // the user assertion goes
  CHECK(vertex_owner.list_tags(TagScope::Local) == std::vector<std::string>{"role.datum"});
  CHECK(vertex_owner.explain_tag("role.datum", TagScope::Local)[0].find("producer")->find("kind")->as_string() == "auto_rule");
  CHECK(vertex_owner.remove_tag_bindings("role.datum", automatic.producer()) == 1);
  CHECK_FALSE(vertex_owner.has_tag("role.datum"));
}

TEST_CASE("internal and legacy bindings are not user assertions") {
  Solid box = box_solid(1, 1, 1);
  box.add_tag("internal.marker");
  CHECK(box.explain_tag("internal.marker", TagScope::Local)[0].find("producer")->find("kind")->as_string() == "auto_rule");

  box.set_legacy_tags({"legacy.marker"});
  const auto legacy = box.explain_tag("legacy.marker");
  REQUIRE(legacy.size() == 1);
  CHECK(legacy[0].find("producer")->find("kind")->as_string() == "legacy_import");
  CHECK(legacy[0].find("attachment")->as_string() == "effective_legacy");
  CHECK(box.has_tag("legacy.marker"));
  CHECK_THROWS_AS((void)box.list_tags(TagScope::Local), UnsupportedQueryCapabilityError);
  CHECK_THROWS_AS((void)box.has_tag("legacy.marker", TagScope::Inherited), UnsupportedQueryCapabilityError);
  CHECK(box.list_tags() == std::vector<std::string>{"legacy.marker"});
}

TEST_CASE("has_tag compares the name as given") {
  Solid box = box_solid(1, 1, 1);
  box.add_tag("box");
  CHECK(box.has_tag("box"));
  CHECK_FALSE(box.has_tag("Box"));         // not normalized: simply absent
  CHECK_THROWS_AS((void)box.explain_tag("Box"), ValueError);
}

TEST_CASE("replace_local_tag_bindings keeps legacy snapshots and swaps the rest") {
  Solid box = box_solid(1, 1, 1);
  box.add_tag("a.one");
  box.replace_local_tag_bindings({user_tag_binding("b.two")});
  CHECK(box.list_tags(TagScope::Local) == std::vector<std::string>{"b.two"});
  const std::string id = box.local_bindings().front().binding_id;
  CHECK(box.remove_tag_binding(id));
  CHECK_FALSE(box.remove_tag_binding(id));
  CHECK_THROWS_AS((void)box.remove_tag_binding(""), ValueError);
}

TEST_CASE("a semantic view carries the tags of every entity and keeps the topo ids") {
  Solid box = box_solid(1, 2, 3);
  Face face = box.faces()[2];
  face.add_tag("face.chosen");
  box.add_binding(user_tag_binding("role.body", UserTagOptions{.topology = TopologyPropagation::Downward}));

  const Shape view = clone_semantic_view(box);
  CHECK_FALSE(view.same_entity(box));
  CHECK(view.has_tag("role.body", TagScope::Local));
  const Solid view_solid(view);
  const Face view_face = view_solid.faces()[2];
  CHECK(view_face.topo_id() == face.topo_id());
  CHECK(view_face.has_tag("face.chosen", TagScope::Local));
  CHECK(view_face.has_tag("role.body", TagScope::Inherited));

  // Independent from here on.
  Face other = view_solid.faces()[2];
  other.add_tag("only.in.view");
  CHECK_FALSE(face.has_tag("only.in.view"));
}

TEST_CASE("the view of a sub-shape handle keeps the ids it had in the source") {
  Solid box = box_solid(1, 2, 3);
  const Face face = box.faces()[3];
  Edge edge = face.edges()[1];
  edge.add_tag("edge.picked");

  const Shape view = clone_semantic_view(face);
  CHECK(view.topo_id() == face.topo_id());
  bool found = false;
  for (const Edge& e : Face(view).edges()) {
    if (e.topo_id() == edge.topo_id()) {
      found = true;
      CHECK(e.has_tag("edge.picked", TagScope::Local));
    }
  }
  CHECK(found);
}

TEST_CASE("copy_semantic_state_from leaves graph and mesh attachments behind") {
  Solid a = box_solid(1, 1, 1), b = box_solid(1, 1, 1);
  a.add_tag("role.copied");
  a.set_metadata("keep", 1);
  a.set_metadata("graph", Value::object());
  a.set_runtime("graph.node_id", "n_1");
  a.set_runtime("mesh.default", 1);
  a.set_runtime("semantic.lineage.coverage", "complete");
  b.copy_semantic_state_from(a);
  CHECK(b.has_tag("role.copied", TagScope::Local));
  CHECK(b.get_metadata("keep").as_int() == 1);
  CHECK(b.get_metadata("graph").is_null());
  CHECK(b.get_runtime("graph.node_id").is_null());
  CHECK(b.get_runtime("mesh.default").is_null());
  CHECK(b.get_runtime("semantic.lineage.coverage").as_string() == "complete");
}
