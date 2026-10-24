// The finalize pipeline: role tags, tag_prefix, tracking projection, recording
// (_support.py; test_operation_output_roles.py, test_tracking_tags.py).
#include "doctest.h"

#include <algorithm>
#include <set>

#include "scad/core/error.hpp"
#include "scad/semantic/autotag.hpp"
#include "scad/semantic/finalize.hpp"
#include "scad/semantic/tracking.hpp"
#include "scad/topo/tag_factories.hpp"
#include "test_tracking_support.hpp"

using namespace scad;
using scad::tracking_test::box_solid;
using scad::tracking_test::cylinder_solid;
using scad::tracking_test::rectangle_face;

namespace {

// A recorder like the reactive Session as far as tags can tell: numbers nodes, hands out
// reservations, and attaches the lineage keys to what it records.
class TestRecorder final : public Recorder {
 public:
  struct Entry {
    OpRecord record;
    std::string node_id;
  };
  std::vector<Entry> entries;

  void record(const OpRecord& record, const std::vector<Shape>& outputs) override {
    const std::string id = record.node_id.empty() ? next("n") : record.node_id;
    entries.push_back({record, id});
    int slot = 0;
    for (Shape output : outputs) {
      output.set_runtime("graph.id", "g_test");
      output.set_runtime("graph.node_id", id);
      output.set_runtime("graph.output_slot", slot++);
    }
  }
  std::optional<NodeReservation> reserve_node(std::string_view prefix) override {
    return NodeReservation{"g_test", next(std::string(prefix))};
  }
  std::vector<std::string> ops() const {
    std::vector<std::string> out;
    for (const auto& e : entries) out.push_back(e.record.op);
    return out;
  }

 private:
  std::string next(const std::string& prefix) { return prefix + "_" + std::to_string(++counter_); }
  int counter_ = 0;
};

template <class T>
std::size_t count_with_tag(const std::vector<T>& shapes, std::string_view tag, TagScope scope = TagScope::Local) {
  return static_cast<std::size_t>(std::count_if(shapes.begin(), shapes.end(), [&](const T& s) { return s.has_tag(tag, scope); }));
}

OpRecord record_for(std::string_view op, std::vector<OpInput> inputs = {}) {
  OpRecord r;
  r.op = std::string(op);
  r.params = Value::object();
  r.inputs = std::move(inputs);
  return r;
}

}  // namespace

TEST_CASE("role tags are normalized against the operation's table") {
  const auto assignments = normalize_operation_role_tags(
      "make_extrude_rsolid", {{"extrusion.side", "part.sides"}, {"extrusion.start", "part.start"}, {"extrusion.end", std::nullopt}});
  REQUIRE(assignments.size() == 2);
  CHECK(assignments[0].role == "extrusion.start");  // table order, not request order
  CHECK(assignments[1].cardinality == RoleCardinality::Many);

  CHECK_THROWS_WITH_AS((void)normalize_operation_role_tags("make_extrude_rsolid", {{"extrusion.start", "A"}}),
                       doctest::Contains("not normalized"), ValueError);
  CHECK_THROWS_AS((void)normalize_operation_role_tags("make_extrude_rsolid", {{"extrusion.start", "a.b"}, {"extrusion.start", "c.d"}}),
                  ValueError);
  try {
    (void)normalize_operation_role_tags("make_extrude_rsolid", {{"box.top", "a.b"}});
    FAIL("an unknown role was accepted");
  } catch (const ValueError& e) {
    CHECK(std::string(e.what()) ==
          "unsupported output role(s) for make_extrude_rsolid: box.top; expected one of extrusion.start, extrusion.end, extrusion.side");
  }
  CHECK_THROWS_AS((void)operation_output_roles("make_nothing"), Exception);
}

TEST_CASE("plan_output_tags fails early on bad names") {
  OutputTags tags;
  tags.result_tag = "Bad Tag";
  CHECK_THROWS_AS((void)plan_output_tags("make_extrude_rsolid", tags), ValueError);
  tags.result_tag = "part.sketch";
  tags.tag_prefix = "  mount ";
  const OutputTagPlan plan = plan_output_tags("make_extrude_rsolid", tags);
  CHECK(*plan.tag_prefix == "mount");
  CHECK(*plan.result_tag == "part.sketch");
}

TEST_CASE("output roles must be kernel-proven with the right cardinality") {
  const Solid solid = box_solid(2, 3, 4);
  TrackedResult tracked = tracked_extrude(rectangle_face(2, 1), {0, 0, 1}, 2.0);
  const auto assignments = normalize_operation_role_tags(
      "make_extrude_rsolid", {{"extrusion.start", "a.start"}, {"extrusion.side", "a.sides"}});
  const auto kinds = validate_operation_output_roles(tracked.delta, assignments);
  CHECK(kinds.at("extrusion.start") == Kind::Face);

  CHECK_THROWS_WITH_AS((void)validate_operation_output_roles(TopoDelta{}, assignments),
                       doctest::Contains("requires exactly one kernel-proven result, got 0"), SemanticCapabilityError);
  const auto side_only = normalize_operation_role_tags("make_extrude_rsolid", {{"extrusion.side", "a.sides"}});
  CHECK_THROWS_WITH_AS((void)validate_operation_output_roles(TopoDelta{}, side_only),
                       doctest::Contains("requires at least one kernel-proven result"), SemanticCapabilityError);
}

TEST_CASE("semantic deltas pick the entity type of the operation") {
  const auto type_of = [](std::string_view op) { return semantic_delta_for_output(op).created.at(0).entity_type; };
  CHECK(type_of("make_point_rvertex") == "Point");
  CHECK(type_of("add_line_rsketch") == "Sketch");
  CHECK(type_of("make_constrain_fix_rsketch") == "Sketch");
  CHECK(type_of("make_circle_wire") == "Profile");
  CHECK(type_of("make_circle_face") == "Sketch");
  CHECK(type_of("make_face_from_wire_rface") == "Sketch");
  CHECK(type_of("make_box_rsolid") == "Body");
  CHECK(type_of("make_extrude_rsolid") == "Feature");
  CHECK(type_of("make_translate_rshape") == "Body");
  CHECK(type_of("something_else") == "ShapeOutput");
  const SemanticDelta two = semantic_delta_for_output("make_extrude_rsolid", 2);
  REQUIRE(two.created.size() == 2);
  CHECK(two.created[1].entity_id == "make_extrude_rsolid:1");
  CHECK(two.created[0].graph_id == "pending");
  CHECK(two.metadata.find("op")->as_string() == "make_extrude_rsolid");
  CHECK(semantic_modified("Part", "p1").modified.at(0).entity_id == "p1");
}

TEST_CASE("an extrusion: tracking projection, role tags, result tag and prefix") {
  const Face profile = rectangle_face(2, 1);
  TrackedResult tracked = tracked_extrude(profile, {0, 0, 1}, 2.0);
  tracked.shape.apply_tag("solid.extrusion");

  FinalizeSpec spec;
  spec.record = record_for("make_extrude_rsolid", {{profile, "profile"}});
  spec.tags.tag_prefix = "part";
  spec.tags.result_tag = "role.result";
  spec.tags.roles = {{"extrusion.start", "role.start_face"}, {"extrusion.end", "role.end_face"}, {"extrusion.side", "role.side_face"}};
  spec.roles.start = "extrusion.start";
  spec.roles.end = "extrusion.end";
  spec.roles.side = "extrusion.side";
  const Solid solid = finalize_tracked_solid(std::move(tracked), std::move(spec));

  const auto faces = solid.faces();
  CHECK(count_with_tag(faces, "role.start_face") == 1);
  CHECK(count_with_tag(faces, "role.end_face") == 1);
  CHECK(count_with_tag(faces, "role.side_face") == 4);
  CHECK(count_with_tag(faces, "part.face.start") == 1);
  CHECK(count_with_tag(faces, "part.face.end") == 1);
  CHECK(count_with_tag(faces, "part.face.side") == 4);
  CHECK(solid.has_tag("part.solid", TagScope::Local));
  CHECK(solid.has_tag("role.result", TagScope::Local));
  CHECK(solid.has_tag("solid.extrusion", TagScope::Local));
  CHECK(count_with_tag(faces, "face.extrusion.start") == 1);  // the kernel-proven role binding

  // The topology-name tags of faces are downward: the face's edges inherit them.
  const Face start = *std::find_if(faces.begin(), faces.end(), [](const Face& f) { return f.has_tag("part.face.start", TagScope::Local); });
  CHECK(start.edges().front().has_tag("part.face.start", TagScope::Inherited));

  // The solid carries the summary, its faces the typed envelope.
  const Value summary = solid.get_metadata("track");
  CHECK(summary.find("op")->as_string() == "make_extrude_rsolid");
  CHECK(summary.find("has_delta")->as_bool());
  const Value track = faces[0].get_metadata("track");
  CHECK(track.find("schema_version")->as_string() == "1.0");
  CHECK(track.find("operation")->as_string() == "extrude");
  CHECK(track.find("topo_kind")->as_string() == "FACE");
}

TEST_CASE("the same finalize records every tag assignment as a graph node") {
  TestRecorder recorder;
  RecorderScope scope(&recorder);
  const Face profile = rectangle_face(2, 1);
  TrackedResult tracked = tracked_extrude(profile, {0, 0, 1}, 2.0);

  FinalizeSpec spec;
  spec.record = record_for("make_extrude_rsolid", {{profile, "profile"}});
  spec.record.params.set("distance", 2.0);
  spec.tags.result_tag = "role.result";
  spec.tags.roles = {{"extrusion.start", "role.start_face"}};
  const Solid solid = finalize_tracked_solid(std::move(tracked), std::move(spec));

  REQUIRE(recorder.ops() == std::vector<std::string>{"make_extrude_rsolid", "apply_tag_rselection", "apply_tag_rselection"});
  const OpRecord& main = recorder.entries[0].record;
  CHECK(main.delta.has_value());
  CHECK(main.delta->roles.size() == 6);
  REQUIRE(main.semantic_delta.has_value());
  CHECK(main.semantic_delta->created.at(0).entity_type == "Feature");

  // Tag assignments are anchored to the node they read and carry deterministic ids.
  const OpRecord& role_node = recorder.entries[1].record;
  const Value binding = *role_node.params.find("tag_binding");
  CHECK(binding.find("scope")->find("node_id")->as_string() == recorder.entries[0].node_id);
  CHECK(binding.find("producer")->find("node_id")->as_string() == recorder.entries[1].node_id);
  CHECK(binding.find("binding_id")->as_string() ==
        "tag_binding_" + uuid5_url_hex("simplecad:user-tag:g_test:" + recorder.entries[1].node_id + ":role.start_face"));
  CHECK(binding.find("evidence")->find("authoring_source")->as_string() == "simplecadapi.make_extrude_rsolid.role_tag");
  CHECK(binding.find("evidence")->find("operation_output_role")->find("role")->as_string() == "extrusion.start");
  CHECK(binding.find("target")->find("selector")->find("predicate")->find("data")->find("role")->as_string() == "extrusion.start");
  CHECK(role_node.inputs.size() == 1);

  // The result is the last assignment's output, a view; the first output is untouched.
  CHECK(solid.get_runtime("graph.node_id").as_string() == recorder.entries[2].node_id);
  CHECK(solid.has_tag("role.result", TagScope::Local));
  CHECK(count_with_tag(solid.faces(), "role.start_face") == 1);
}

TEST_CASE("box face roles and tag_prefix name exactly one face each") {
  const Face dummy_profile = rectangle_face(1, 1);
  TrackedResult tracked = tracked_box({-1, -1.5, 0}, 2.0, 3.0, 4.0);
  FinalizeSpec spec;
  spec.record = record_for("make_box_rsolid");
  spec.tags.tag_prefix = "housing";
  spec.tags.result_tag = "part.housing";
  spec.tags.roles = {{"box.bottom", "anchor.base"}, {"box.right", "role.mounting_surface"}};
  spec.roles.faces = {{"box.bottom", "bottom"}, {"box.top", "top"}, {"box.front", "front"},
                      {"box.back", "back"},     {"box.left", "left"}, {"box.right", "right"}};
  const Solid box = finalize_tracked_solid(std::move(tracked), std::move(spec));

  const auto faces = box.faces();
  for (const char* tag : {"housing.face.bottom", "housing.face.top", "housing.face.front", "housing.face.back",
                          "housing.face.left", "housing.face.right", "anchor.base", "role.mounting_surface"})
    CHECK_MESSAGE(count_with_tag(faces, tag) == 1, tag);
  CHECK(box.has_tag("housing.solid", TagScope::Local));
  CHECK(box.has_tag("part.housing", TagScope::Local));
  (void)dummy_profile;
}

TEST_CASE("a prefix on an extrusion names side faces after the profile's edge tags") {
  Face profile = rectangle_face(2, 1);
  const Shape tagged_profile =
      apply_profile_tag_prefix(profile, std::nullopt, std::vector<std::string>{"a", "b", "c", "d"}, "simplecadapi.test");
  CHECK(count_with_tag(profile.edges(), "a") == 1);

  TrackedResult tracked = tracked_extrude(Face(tagged_profile), {0, 0, 1}, 3.0);
  FinalizeSpec spec;
  spec.record = record_for("make_extrude_rsolid", {{tagged_profile, "profile"}});
  spec.tags.tag_prefix = "swept";
  spec.roles.start = "extrusion.start";
  spec.roles.end = "extrusion.end";
  spec.roles.side = "extrusion.side";
  const Solid solid = finalize_tracked_solid(std::move(tracked), std::move(spec));

  std::set<std::string> side_tags;
  for (const Face& face : solid.faces())
    for (const auto& tag : face.list_tags(TagScope::Local))
      if (tag.rfind("swept.face.side.", 0) == 0) side_tags.insert(tag);
  CHECK(side_tags == std::set<std::string>{"swept.face.side.a", "swept.face.side.b", "swept.face.side.c", "swept.face.side.d"});
  CHECK(count_with_tag(solid.faces(), "swept.face.side") == 4);
}

TEST_CASE("profile prefixes tag the shape and its edges") {
  Face profile = rectangle_face(2, 1);
  const Shape out = apply_profile_tag_prefix(profile, std::string("prof"), std::nullopt, "simplecadapi.test");
  CHECK(out.has_tag("prof.face", TagScope::Local));
  const auto edges = profile.edges();
  CHECK(count_with_tag(edges, "prof.edge.line1") == 1);
  CHECK(count_with_tag(edges, "prof.edge.line4") == 1);
  CHECK_THROWS_WITH_AS((void)apply_profile_tag_prefix(profile, std::nullopt, std::vector<std::string>{"a"}, "x"),
                       "edge_tags must contain exactly 4 tags, got 1", ValueError);
  // Face-kind topology names are downward, edge ones local: the recorded identity says which.
  const TagBinding& binding = *std::find_if(profile.local_bindings().begin(), profile.local_bindings().end(),
                                            [](const TagBinding& b) { return b.tag == "prof.face"; });
  CHECK(binding.propagation().topology == TopologyPropagation::Downward);
  CHECK(binding.evidence->data.find("topology_name")->find("local_name")->as_string() == "face");
}

TEST_CASE("user tags follow a cut only through proven lineage") {
  Solid body = box_solid(10, 10, 10);
  for (Face& face : body.faces()) face.add_binding(user_tag_binding("role.source_face"));
  const Solid tool = cylinder_solid(2.0, 15.0, {3, 3, -2.5});

  TrackedBooleanResult cut = tracked_cut(body, tool);
  REQUIRE(cut.solid.has_value());
  FinalizeSpec spec;
  spec.record = record_for("make_cut_rsolid", {{body, "body"}, {tool, "tool"}});
  const Solid result = finalize_tracked_solid(std::move(cut), std::move(spec));

  bool lineage_seen = false;
  for (const Face& face : result.faces()) {
    const Value track = face.get_metadata("track");
    CHECK(track.find("kind")->as_string() == "topology_change");
    const bool from_body = std::any_of(track.find("origin_roles")->as_array().begin(), track.find("origin_roles")->as_array().end(),
                                       [](const Value& v) { return v.as_string() == "body"; });
    if (from_body && track.find("status")->as_string() == "proven") {
      CHECK_FALSE(face.has_tag("role.source_face", TagScope::Effective));
      const std::string coverage = face.get_runtime("semantic.lineage.coverage").as_string();
      if (coverage == "complete" && face.has_tag("role.source_face", TagScope::Lineage)) lineage_seen = true;
    }
  }
  CHECK(lineage_seen);
  for (const Edge& edge : result.edges()) {
    const Value track = edge.get_metadata("track");
    CHECK(track.find("topo_kind")->as_string() == "EDGE");
    CHECK(track.find("kind")->as_string() == "topology_change");
  }
}

TEST_CASE("faces without matching evidence stay partial and unknown") {
  Solid box = box_solid(1, 1, 1);
  apply_tracking_tags(box, TopoDelta{}, {}, TrackingContext{"cut", {}});
  for (const Face& face : box.faces()) {
    const Value track = face.get_metadata("track");
    CHECK(track.find("coverage")->as_string() == "partial");
    CHECK(track.find("status")->as_string() == "unknown");
    CHECK(track.find("events")->size() == 0);
    CHECK(track.find("witnesses")->size() == 0);
    CHECK(face.get_runtime("semantic.lineage.coverage").as_string() == "partial");
  }
  CHECK(operation_alias("make_box_rsolid") == "box");
  CHECK(operation_alias("op.make_cut_rsolid") == "cut");
  CHECK(operation_alias("Extrude") == "extrude");
}

TEST_CASE("the graph tracking policy records without a delta and projects nothing") {
  TrackingPolicyScope policy(TrackingPolicy::Graph);
  TestRecorder recorder;
  RecorderScope scope(&recorder);
  TrackedResult tracked = tracked_extrude(rectangle_face(1, 1), {0, 0, 1}, 1.0);
  FinalizeSpec spec;
  spec.record = record_for("make_extrude_rsolid");
  const Solid solid = finalize_tracked_solid(std::move(tracked), std::move(spec));
  REQUIRE(recorder.entries.size() == 1);
  CHECK_FALSE(recorder.entries[0].record.delta.has_value());
  CHECK_FALSE(solid.get_metadata("track").find("has_delta"));
  CHECK(solid.faces().front().get_metadata("track").is_null());
}

TEST_CASE("primitives and derived shapes record with their semantic delta") {
  TestRecorder recorder;
  RecorderScope scope(&recorder);
  Solid box = box_solid(1, 1, 1);
  OpRecord rec = record_for("make_box_rsolid");
  rec.labels = {"primitive"};
  const Solid out = finalize_primitive(box, rec);
  REQUIRE(recorder.entries.size() == 1);
  CHECK(recorder.entries[0].record.labels == std::vector<std::string>{"primitive"});
  CHECK(recorder.entries[0].record.semantic_delta->created.at(0).entity_type == "Body");
  CHECK(out.get_metadata("track").find("op")->as_string() == "make_box_rsolid");

  finalize_runtime_object(record_for("make_sketch_rsketch"));
  CHECK(recorder.entries.back().record.semantic_delta->created.at(0).entity_type == "Sketch");
  CHECK(recorder.entries.back().record.semantic_delta->created.at(0).entity_id == "make_sketch_rsketch:0");
}

TEST_CASE("semantic ids are unique within a recorded session only") {
  reserve_semantic_id("part", "p1");
  reserve_semantic_id("part", "p1");  // no session: nothing is tracked
  TestRecorder recorder;
  RecorderScope scope(&recorder);
  reserve_semantic_id("part", "p1");
  reserve_semantic_id("assembly", "p1");
  CHECK_THROWS_WITH_AS(reserve_semantic_id("part", "p1"), doctest::Contains("duplicate part id in active GraphSession: p1"), ValueError);
}

TEST_CASE("lineage helpers carry only what the policy allows") {
  Solid source = box_solid(1, 1, 1);
  Solid target = box_solid(2, 2, 2);
  source.add_binding(user_tag_binding("role.keep"));
  source.add_binding(user_tag_binding("role.drop", UserTagOptions{.lineage = LineagePolicy::None}));
  source.set_runtime("semantic.lineage.coverage", "partial");

  attach_lineage_from_source(source, target, LineageDerivation::Continuation, "make_translate_rshape");
  CHECK(target.get_runtime("semantic.lineage.coverage").as_string() == "partial");
  REQUIRE(target.lineage_witnesses().size() == 1);
  CHECK(target.lineage_witnesses()[0].binding.tag == "role.keep");
  CHECK(target.lineage_witnesses()[0].coverage == "partial");
  CHECK(target.lineage_witnesses()[0].source_topo_id == source.topo_id());

  // A second hop carries the witnessed binding on.
  Solid third = box_solid(3, 3, 3);
  target.set_runtime("semantic.lineage.coverage", "complete");
  attach_lineage_from_source(target, third, LineageDerivation::Continuation, "make_translate_rshape");
  CHECK(third.lineage_witnesses().size() == 1);
  CHECK(third.get_runtime("semantic.lineage.coverage").as_string() == "complete");

  const auto merged = merge_topo_deltas({TopoDelta{}, TopoDelta{}});
  REQUIRE(merged.has_value());
  CHECK(merged->raw_event.find("steps")->size() == 2);
  CHECK_FALSE(merge_topo_deltas({}).has_value());
}

TEST_CASE("the call-site in finalize.hpp's header comment compiles as written") {
  const Face profile = rectangle_face(2, 1);
  const std::optional<std::string> tag_prefix = "mount", result_tag = "part.mount", start_face_tag = "role.first";
  const std::optional<std::string> none;
  const char* kOp = "make_extrude_rsolid";
  OutputTags tags{.tag_prefix = tag_prefix,
                  .result_tag = result_tag,
                  .roles = {{"extrusion.start", start_face_tag}, {"extrusion.end", none}, {"extrusion.side", none}}};
  (void)plan_output_tags(kOp, tags);
  TrackedResult tracked = tracked_extrude(profile, {0, 0, 1}, 1.0);
  tracked.shape.apply_tag("solid.extrusion", false);
  const Solid solid = finalize_tracked_solid(
      std::move(tracked),
      {.record = {.op = kOp, .params = Value::object(), .inputs = {{profile, "profile"}}},
       .tags = tags,
       .roles = {.start = "extrusion.start", .end = "extrusion.end", .side = "extrusion.side"}});
  CHECK(solid.has_tag("mount.solid", TagScope::Local));
  CHECK(count_with_tag(solid.faces(), "role.first") == 1);
  CHECK(count_with_tag(solid.faces(), "mount.face.end") == 1);
}
