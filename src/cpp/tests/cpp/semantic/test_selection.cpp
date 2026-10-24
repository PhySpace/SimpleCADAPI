// The public tag operators (operators/selection.py) and tag assignment.
#include "doctest.h"

#include <algorithm>

#include "scad/core/error.hpp"
#include "scad/semantic/finalize.hpp"
#include "scad/semantic/selection.hpp"
#include "scad/semantic/tracking.hpp"
#include "scad/topo/tag_factories.hpp"
#include "test_tracking_support.hpp"

using namespace scad;
using scad::tracking_test::box_solid;

namespace {

bool contains(const std::vector<std::string>& list, std::string_view item) {
  return std::find(list.begin(), list.end(), item) != list.end();
}

// A selector that picks faces of its scope by position, standing in for QL.
class FixedSelector final : public ShapeSelector {
 public:
  explicit FixedSelector(std::vector<std::size_t> picks, std::optional<SelectorSource> source = std::nullopt)
      : picks_(std::move(picks)), source_(std::move(source)) {}
  std::vector<Shape> resolve(const Shape& scope) const override {
    const auto faces = Solid(scope).faces();
    std::vector<Shape> out;
    for (const std::size_t i : picks_) out.push_back(faces.at(i));
    return out;
  }
  Value to_value() const override {
    Value v = Value::object();
    v.set("target_kind", "face");
    return v;
  }
  std::optional<SelectorSource> source() const override { return source_; }

 private:
  std::vector<std::size_t> picks_;
  std::optional<SelectorSource> source_;
};

class AnchoringRecorder final : public Recorder {
 public:
  std::vector<OpRecord> records;
  void record(const OpRecord& record, const std::vector<Shape>& outputs) override {
    records.push_back(record);
    for (Shape output : outputs) output.set_runtime("graph.node_id", "n_out");
  }
  std::optional<NodeReservation> reserve_node(std::string_view) override { return NodeReservation{"g_x", "n_reserved"}; }
};

}  // namespace

TEST_CASE("apply_tag tags the shape itself, locally, with continuation/fragment lineage") {
  Solid box = box_solid(1, 1, 1);
  const Shape back = apply_tag(box, "role.structure");
  CHECK(back.same_entity(box));
  CHECK(contains(list_tags(box, TagScope::Local), "role.structure"));
  CHECK(list_tags(box.faces()[0]).empty());
  CHECK_FALSE(contains(list_tags(box.faces()[0]), "role.structure"));

  const auto explained = explain_tag(box, "role.structure", TagScope::Local);
  REQUIRE(explained.size() == 1);
  const Value binding = *explained[0].find("binding");
  CHECK(explained[0].find("producer")->find("kind")->as_string() == "user_operation");
  CHECK(binding.find("propagation")->find("lineage")->as_string() == "continuation_fragment");
  CHECK(binding.find("target")->find("kind")->as_string() == "selection_query");
  CHECK(binding.find("target")->find("selector")->dump() ==
        R"({"target_kind":"solid","order_desc":false,"cardinality":{"exactly":1}})");
  CHECK(binding.find("evidence")->find("kind")->as_string() == "query_execution");
  CHECK(binding.find("evidence")->find("authoring_source")->as_string() == "simplecadapi.apply_tag_rselection");
  CHECK(binding.find("evidence")->find("selected_count")->as_int() == 1);
  CHECK(binding.find("evidence")->find("selected_refs")->as_array().at(0).dump() ==
        std::string(R"({"kind":"solid","topo_id":")") + box.topo_id() + "\"}");
}

TEST_CASE("apply_tag_rselection leaves its scope alone and returns an independent view") {
  Solid box = box_solid(1, 1, 1);
  const Face source_face = box.faces()[0];

  const Shape tagged = apply_tag_rselection(box, TagTargets(std::vector<Face>{source_face}), "role.mounting_surface");
  CHECK_FALSE(tagged.same_entity(box));
  CHECK_FALSE(box.has_tag("role.mounting_surface"));
  CHECK_FALSE(box.faces()[0].has_tag("role.mounting_surface"));

  const Solid tagged_solid(tagged);
  const Face tagged_face = tagged_solid.faces()[0];
  CHECK(tagged_face.topo_id() == source_face.topo_id());
  CHECK(list_tags(tagged_face, TagScope::Local) == std::vector<std::string>{"role.mounting_surface"});
  const auto explanation = explain_tag(tagged_face, "role.mounting_surface", TagScope::Local);
  REQUIRE(explanation.size() == 1);
  CHECK(explanation[0].find("producer")->find("kind")->as_string() == "user_operation");
  const Value target = *explanation[0].find("binding")->find("target");
  CHECK(target.find("kind")->as_string() == "explicit_refs");
  CHECK(target.find("refs")->as_array().at(0).find("topo_id")->as_string() == source_face.topo_id());
}

TEST_CASE("targets must belong to the scope and be distinct") {
  Solid box = box_solid(1, 1, 1);
  const Solid other = box_solid(1, 1, 1);
  CHECK_THROWS_AS((void)apply_tag_rselection(box, TagTargets(std::vector<Face>{other.faces()[0]}), "role.x"), Error);
  try {
    (void)apply_tag_rselection(box, TagTargets(std::vector<Face>{other.faces()[0]}), "role.x");
  } catch (const Error& e) {
    CHECK(e.operation() == "apply_tag_rselection");
    CHECK(e.guidance().what_happened == "Failed to attach the tag to the selected shapes.");
    CHECK(e.guidance().technical_details.find("tag target does not belong to the assignment scope") != std::string::npos);
  }
  const Face face = box.faces()[0];
  CHECK_THROWS_AS((void)assign_tag(box, TagTargets(std::vector<Face>{face, face}), "role.x", TopologyPropagation::Local,
                                   LineagePolicy::ContinuationFragment),
                  ValueError);
  CHECK_THROWS_AS((void)assign_tag(box, TagTargets(std::vector<Face>{}), "role.x", TopologyPropagation::Local,
                                   LineagePolicy::ContinuationFragment),
                  ValueError);
  CHECK_THROWS_AS((void)assign_tag(box, TagTargets(std::make_shared<FixedSelector>(std::vector<std::size_t>{})), "role.x",
                                   TopologyPropagation::Local, LineagePolicy::ContinuationFragment),
                  ValueError);
}

TEST_CASE("a selector picks the targets and is recorded in the binding") {
  Solid box = box_solid(1, 1, 1);
  const Shape tagged = apply_tag_rselection(box, TagTargets(std::make_shared<FixedSelector>(std::vector<std::size_t>{1, 2})),
                                            "role.pair", TopologyPropagation::Downward);
  const Solid view(tagged);
  CHECK(view.faces()[1].has_tag("role.pair", TagScope::Local));
  CHECK(view.faces()[2].has_tag("role.pair", TagScope::Local));
  CHECK_FALSE(view.faces()[0].has_tag("role.pair", TagScope::Local));
  CHECK(view.faces()[1].edges().front().has_tag("role.pair", TagScope::Inherited));
  const auto explained = explain_tag(view.faces()[1], "role.pair", TagScope::Local);
  CHECK(explained[0].find("binding")->find("propagation")->find("topology")->as_string() == "downward");
  CHECK(explained[0].find("binding")->find("evidence")->find("selected_count")->as_int() == 2);
}

TEST_CASE("select_faces_by_tag and select_edges_by_tag honour the scope") {
  Solid box = box_solid(1, 1, 1);
  box.auto_tag_faces("box");
  CHECK(select_faces_by_tag(box, "face.top").size() == 1);
  CHECK(select_faces_by_tag(box, "face.top", TagScope::Inherited).empty());
  CHECK(select_edges_by_tag(box, "edge.boundary").size() == 12);
  CHECK(select_edges_by_tag(box.faces()[0], "edge.boundary").size() == 4);

  try {
    (void)select_edges_by_tag(box.faces()[0].edges()[0], "edge.boundary");
    FAIL("an edge is neither a face nor a solid");
  } catch (const Error& e) {
    CHECK(e.operation() == "select_edges_by_tag");
  }
  try {
    (void)select_faces_by_tag(box, "Not Normal");
    FAIL("a malformed tag was accepted");
  } catch (const Error& e) {
    CHECK(e.operation() == "select_faces_by_tag");
    CHECK(e.guidance().technical_details.find("ValueError") != std::string::npos);
  }
  try {
    (void)explain_tag(box, "bad tag");
    FAIL("a malformed tag was accepted");
  } catch (const Error& e) {
    CHECK(e.operation() == "explain_tag");
  }
}

TEST_CASE("the native selectors serialise like QL's and check their cardinality") {
  CHECK(NativeSelector::exactly_one(Kind::Face)->to_value().dump() ==
        R"({"target_kind":"face","order_desc":false,"cardinality":{"exactly":1}})");
  CHECK(NativeSelector::with_output_role(Kind::Face, " Extrusion.Start ", false)->to_value().dump() ==
        R"({"target_kind":"face","order_desc":false,"cardinality":{"at_least":1},)"
        R"("predicate":{"kind":"output_role","data":{"role":"extrusion.start"},"children":[]}})");
  const auto anchored = NativeSelector::exactly_one(Kind::Solid)->from_source({"n_4", 2});
  REQUIRE(anchored);
  CHECK(anchored->to_value().dump() ==
        R"({"target_kind":"solid","order_desc":false,"cardinality":{"exactly":1},"source_node_id":"n_4","source_output_slot":2})");
  CHECK(anchored->source()->node_id == "n_4");

  const Solid box = box_solid(1, 1, 1);
  CHECK(NativeSelector::exactly_one(Kind::Solid)->resolve(box).size() == 1);
  try {
    (void)NativeSelector::exactly_one(Kind::Face)->resolve(box);
    FAIL("a box has six faces");
  } catch (const Error& e) {
    CHECK(e.operation() == "ql.face.resolve");
    CHECK(e.guidance().what_happened == "QL selector expected exactly 1 face(s), got 6");
  }
  CHECK_THROWS_AS((void)NativeSelector::exactly_one(Kind::Shell)->resolve(box), TypeError);
  CHECK_THROWS_AS((void)NativeSelector::with_output_role(Kind::Face, "  ", true), ValueError);
}

TEST_CASE("under a recorder an assignment is a node anchored to its scope") {
  AnchoringRecorder recorder;
  RecorderScope scope(&recorder);
  Solid box = box_solid(1, 1, 1);
  box.set_runtime("graph.node_id", "n_box");
  box.set_runtime("graph.output_slot", 1);

  const Shape tagged = apply_tag_rselection(box, TagTargets(NativeSelector::exactly_one(Kind::Solid)), "role.a");
  REQUIRE(recorder.records.size() == 1);
  const OpRecord& record = recorder.records[0];
  CHECK(record.op == "apply_tag_rselection");
  CHECK(record.node_id == "n_reserved");
  CHECK(record.inputs.at(0).shape.same_entity(box));
  const Value binding = *record.params.find("tag_binding");
  CHECK(binding.find("scope")->dump() == R"({"node_id":"n_box","output_slot":1})");
  CHECK(binding.find("target")->find("selector")->find("source_node_id")->as_string() == "n_box");
  CHECK(binding.find("target")->find("selector")->find("source_output_slot")->as_int() == 1);
  CHECK(binding.find("binding_id")->as_string() ==
        "tag_binding_" + uuid5_url_hex("simplecad:user-tag:g_x:n_reserved:role.a"));
  CHECK(tagged.get_runtime("graph.node_id").as_string() == "n_out");
  CHECK(box.get_runtime("graph.node_id").as_string() == "n_box");  // the scope keeps its own node

  // A selector anchored somewhere else cannot be used on this scope.
  CHECK_THROWS_AS((void)assign_tag(box, TagTargets(std::make_shared<FixedSelector>(std::vector<std::size_t>{0}, SelectorSource{"n_other", 0})),
                                   "role.b", TopologyPropagation::Local, LineagePolicy::ContinuationFragment),
                  ValueError);
}

TEST_CASE("apply_tag marks the shape itself, apply_tag_rselection works on a clone") {
  Solid box = box_solid(1, 1, 1);

  std::size_t before = Shape::clone_view_count();
  box.apply_tag("role.structure");
  CHECK(Shape::clone_view_count() == before);  // the shape is tagged in place, nothing is copied
  CHECK(box.has_tag("role.structure", TagScope::Local));

  before = Shape::clone_view_count();
  const Shape tagged = apply_tag_rselection(box, TagTargets(std::vector<Shape>{box}), "role.other");
  CHECK(Shape::clone_view_count() > before);  // the scope is cloned: it stays as it was
  CHECK_FALSE(box.has_tag("role.other"));
  CHECK(tagged.has_tag("role.other", TagScope::Local));
}
