// The tag view over hand-built graphs: which bindings each witness carries, by lineage policy.
#include "doctest.h"

#include <algorithm>

#include "scad/reactive/graph.hpp"
#include "scad/reactive/tag_view.hpp"
#include "scad/topo/tag_factories.hpp"

using namespace scad;
using namespace scad::reactive;

namespace {

TopoRef face_ref(const std::string& node, const std::string& id, Kind kind = Kind::Face) {
  return TopoRef{"g", node, 0, kind, std::string(kind_name(kind)) + "_" + id};
}

TopoEntry witness(TopoRef out, TopoEvent event, std::vector<TopoRef> parents, const char* derivation,
                  bool project = false) {
  TopoEntry e;
  e.ref = std::move(out);
  e.event = event;
  e.parent_refs = std::move(parents);
  e.metadata = Value::object();
  e.metadata.set("derivation", derivation);
  if (project)
    e.metadata.set("project_source_tags", true);
  return e;
}

Value tag_payload(const std::string& tag, const TopoRef& target, LineagePolicy lineage) {
  UserTagOptions options;
  TagTarget explicit_target;
  explicit_target.kind = TagTargetKind::ExplicitRefs;
  explicit_target.refs.push_back(scad::to_value(target));
  options.target = explicit_target;
  options.lineage = lineage;
  Value params = Value::object();
  params.set("tag_binding", user_tag_binding(tag, options).to_value());
  return params;
}

struct G {
  OperationGraph graph{"g"};
  NodePtr add(const std::string& id, const std::string& op, std::vector<NodePtr> inputs,
              std::optional<std::vector<TopoEntry>> entries = std::nullopt, Value params = Value::object()) {
    NodeSpec spec;
    spec.node_id = id;
    spec.op = op;
    spec.params = std::move(params);
    for (const NodePtr& input : inputs)
      spec.bindings.push_back(InputBinding{input->node_id, 0, {}});
    spec.inputs = std::move(inputs);
    if (entries) {
      TopoDelta delta;
      delta.entries = std::move(*entries);
      spec.topo_delta = std::move(delta);
    }
    return graph.add_node(std::move(spec));
  }
};

std::vector<std::string> tags_at(const NodePtr& node, const TopoRef& entity) {
  const auto view = tag_view(node);
  const auto found = view->find(tag_view_key(entity.output_slot, entity.kind, entity.topo_id));
  std::vector<std::string> out;
  if (found != view->end())
    for (const CarriedTag& tag : found->second)
      out.push_back(tag.binding.tag.str());
  std::sort(out.begin(), out.end());
  return out;
}

const std::vector<std::string> kTop{"user.top"};

}  // namespace

TEST_CASE("a tag rides the witnesses of every later operation") {
  G g;
  const NodePtr box = g.add("a", "make_box_rsolid", {});
  const NodePtr tagged = g.add("t", "apply_tag_rselection", {box}, std::nullopt,
                               tag_payload("user.top", face_ref("a", "face_5"), LineagePolicy::ContinuationFragment));
  CHECK(tags_at(tagged, face_ref("t", "face_5")) == kTop);
  // The cut names its input face by the node that made it (the box), behind the tag node.
  const NodePtr cut = g.add(
      "c", "make_cut_rsolid", {tagged},
      std::vector{witness(face_ref("c", "face_2"), TopoEvent::Modified, {face_ref("a", "face_5")}, "fragment"),
                  witness(face_ref("c", "face_7"), TopoEvent::Modified, {face_ref("a", "face_5")}, "fragment"),
                  witness(face_ref("c", "face_0"), TopoEvent::Preserved, {face_ref("a", "face_0")}, "continuation")});
  CHECK(tags_at(cut, face_ref("c", "face_2")) == kTop);  // both pieces of the split face
  CHECK(tags_at(cut, face_ref("c", "face_7")) == kTop);
  CHECK(tags_at(cut, face_ref("c", "face_0")).empty());
  const NodePtr moved = g.add(
      "m", "make_translate_rshape", {cut},
      std::vector{witness(face_ref("m", "face_2"), TopoEvent::Modified, {face_ref("c", "face_2")}, "continuation")});
  CHECK(tags_at(moved, face_ref("m", "face_2")) == kTop);
  // An operation without history ends it.
  const NodePtr offset = g.add("o", "make_offset_rsolid", {moved});
  CHECK(tags_at(offset, face_ref("o", "face_2")).empty());
}

TEST_CASE("the lineage policy decides which derivations a tag follows") {
  G g;
  const NodePtr box = g.add("a", "make_box_rsolid", {});
  const NodePtr tagged = g.add("t", "apply_tag_rselection", {box}, std::nullopt,
                               tag_payload("user.top", face_ref("a", "face_5"), LineagePolicy::Continuation));
  const NodePtr cut =
      g.add("c", "make_cut_rsolid", {tagged},
            std::vector{witness(face_ref("c", "face_2"), TopoEvent::Modified, {face_ref("a", "face_5")}, "fragment")});
  CHECK(tags_at(cut, face_ref("c", "face_2")).empty());  // a fragment is no continuation
  const NodePtr moved = g.add(
      "m", "make_translate_rshape", {tagged},
      std::vector{witness(face_ref("m", "face_5"), TopoEvent::Modified, {face_ref("a", "face_5")}, "continuation")});
  CHECK(tags_at(moved, face_ref("m", "face_5")) == kTop);

  const NodePtr local = g.add("l", "apply_tag_rselection", {box}, std::nullopt,
                              tag_payload("user.top", face_ref("a", "face_5"), LineagePolicy::None));
  const NodePtr kept = g.add(
      "k", "make_translate_rshape", {local},
      std::vector{witness(face_ref("k", "face_5"), TopoEvent::Preserved, {face_ref("a", "face_5")}, "continuation")});
  CHECK(tags_at(kept, face_ref("k", "face_5")).empty());  // `none` stays on the tagged output
}

TEST_CASE("a generated entity is no continuation of its source") {
  // The fillet patch an edge generates is named after the edge by the fillet itself (a projected binding stored
  // on the patch when the fillet runs); the view only follows entities that live on.
  G g;
  const NodePtr box = g.add("a", "make_box_rsolid", {});
  const TopoRef edge = face_ref("a", "edge_1", Kind::Edge);
  const NodePtr tagged = g.add("t", "apply_tag_rselection", {box}, std::nullopt,
                               tag_payload("seam.d", edge, LineagePolicy::ContinuationFragment));
  Value edge_kind = Value::object();
  edge_kind.set("target_kind", "edge");
  const NodePtr pick = g.add("s", "make_select_redge", {tagged}, std::nullopt, edge_kind);
  CHECK(tags_at(pick, face_ref("s", "edge_1", Kind::Edge)) == std::vector<std::string>{"seam.d"});
  const NodePtr fillet = g.add("f", "make_fillet_rsolid", {tagged, pick},
                               std::vector{witness(face_ref("f", "face_9"), TopoEvent::Generated,
                                                   {face_ref("s", "edge_1", Kind::Edge)}, "boundary", true),
                                           witness(face_ref("f", "edge_3", Kind::Edge), TopoEvent::Modified,
                                                   {face_ref("a", "edge_1", Kind::Edge)}, "fragment")});
  CHECK(tags_at(fillet, face_ref("f", "face_9")).empty());
  // A face selection passes no edge on.
  Value face_kind = Value::object();
  face_kind.set("target_kind", "face");
  const NodePtr faces = g.add("p", "make_select_rface", {tagged}, std::nullopt, face_kind);
  CHECK(tags_at(faces, face_ref("p", "edge_1", Kind::Edge)).empty());
  CHECK(tags_at(fillet, face_ref("f", "edge_3", Kind::Edge)) == std::vector<std::string>{"seam.d"});
}
