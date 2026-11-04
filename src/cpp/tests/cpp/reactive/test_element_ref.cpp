// resolve_by_history over hand-built graphs: every status and reason, without a kernel.
#include "doctest.h"

#include <algorithm>

#include "scad/reactive/element_ref.hpp"
#include "scad/reactive/graph.hpp"

using namespace scad;
using namespace scad::reactive;

namespace {

TopoRef ref(const std::string& node, Kind kind, const std::string& topo_id) {
  return TopoRef{"g", node, 0, kind, topo_id};
}
TopoRef face(const std::string& node, const std::string& id) {
  return ref(node, Kind::Face, "face_" + id);
}

TopoEntry entry(TopoRef out, TopoEvent event, std::vector<TopoRef> parents) {
  TopoEntry e;
  e.ref = std::move(out);
  e.event = event;
  e.parent_refs = std::move(parents);
  e.metadata = Value::object();
  e.metadata.set("derivation", event == TopoEvent::Preserved ? "continuation" : "fragment");
  return e;
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

const ElementAnchor kTop{"a", 0, Kind::Face, "face_face_5"};

std::vector<std::string> ids(const ResolvedRef& r) {
  std::vector<std::string> out;
  for (const TopoRef& t : r.targets)
    out.push_back(t.node_id + ":" + t.topo_id);
  return out;
}

}  // namespace

TEST_CASE("a face followed through preserved and modified hops stays one face") {
  G g;
  const NodePtr a = g.add("a", "make_box_rsolid", {}, std::vector<TopoEntry>{});
  const NodePtr b = g.add("b", "make_cut_rsolid", {a},
                          std::vector{entry(face("b", "face_2"), TopoEvent::Modified, {face("a", "face_5")})});
  const NodePtr c = g.add("c", "make_fillet_rsolid", {b},
                          std::vector{entry(face("c", "face_7"), TopoEvent::Preserved, {face("b", "face_2")})});
  const ResolvedRef r = resolve_by_history(c, kTop);
  CHECK(r.status == RefStatus::Ok);
  CHECK(ids(r) == std::vector<std::string>{"c:face_face_7"});
  REQUIRE(r.hops.size() == 2);
  CHECK(r.hops[0].event == TopoEvent::Modified);
  CHECK(r.hops[1].event == TopoEvent::Preserved);
  // Resolving at an intermediate node stops there.
  CHECK(ids(resolve_by_history(b, kTop)) == std::vector<std::string>{"b:face_face_2"});
  // The anchor node itself resolves to the anchor.
  CHECK(ids(resolve_by_history(a, kTop)) == std::vector<std::string>{"a:face_face_5"});
}

TEST_CASE("a face cut in two is a split, never one of the two") {
  G g;
  const NodePtr a = g.add("a", "make_box_rsolid", {});
  const NodePtr b = g.add("b", "make_cut_rsolid", {a},
                          std::vector{entry(face("b", "face_1"), TopoEvent::Modified, {face("a", "face_5")}),
                                      entry(face("b", "face_4"), TopoEvent::Modified, {face("a", "face_5")})});
  const ResolvedRef r = resolve_by_history(b, kTop);
  CHECK(r.status == RefStatus::Split);
  CHECK(ids(r) == std::vector<std::string>{"b:face_face_1", "b:face_face_4"});
}

TEST_CASE("a face unified with a face of another body is merged") {
  G g;
  const NodePtr a = g.add("a", "make_box_rsolid", {});
  const NodePtr t = g.add("t", "make_box_rsolid", {});
  const NodePtr u = g.add("u", "make_union_rsolid", {a, t},
                          std::vector{entry(face("u", "face_4"), TopoEvent::Modified, {face("a", "face_5")}),
                                      entry(face("u", "face_4"), TopoEvent::Modified, {face("t", "face_5")})});
  const ResolvedRef r = resolve_by_history(u, kTop);
  CHECK(r.status == RefStatus::Merged);
  CHECK(ids(r) == std::vector<std::string>{"u:face_face_4"});
}

TEST_CASE("a lost reference says where and why") {
  G g;
  const NodePtr a = g.add("a", "make_box_rsolid", {});
  SUBCASE("deleted") {
    const NodePtr b = g.add("b", "make_cut_rsolid", {a},
                            std::vector{entry(face("a", "face_5"), TopoEvent::Deleted, {face("a", "face_5")})});
    const ResolvedRef r = resolve_by_history(b, kTop);
    CHECK(r.status == RefStatus::Lost);
    CHECK(r.reason == "deleted");
    CHECK(r.lost_at == "b");
  }
  SUBCASE("only generated something else: replaced in identity mode") {
    const NodePtr b = g.add("b", "make_shell_rsolid", {a},
                            std::vector{entry(face("b", "face_9"), TopoEvent::Generated, {face("a", "face_5")})});
    const ResolvedRef r = resolve_by_history(b, kTop);
    CHECK(r.status == RefStatus::Lost);
    CHECK(r.reason == "replaced");
    // Derived mode follows the generated face.
    CHECK(ids(resolve_by_history(b, kTop, 0, FollowMode::Derived)) == std::vector<std::string>{"b:face_face_9"});
  }
  SUBCASE("an operation with no history") {
    const NodePtr b = g.add("b", "make_offset_rsolid", {a});
    const ResolvedRef r = resolve_by_history(b, kTop);
    CHECK(r.status == RefStatus::Lost);
    CHECK(r.reason == "no_history");
    CHECK(r.lost_at == "b");
  }
  SUBCASE("history that does not mention the face") {
    const NodePtr b = g.add("b", "make_cut_rsolid", {a},
                            std::vector{entry(face("b", "face_0"), TopoEvent::Preserved, {face("a", "face_0")})});
    CHECK(resolve_by_history(b, kTop).reason == "no_history");
  }
  SUBCASE("a target that does not descend from the anchor") {
    const NodePtr other = g.add("o", "make_box_rsolid", {});
    const ResolvedRef r = resolve_by_history(other, kTop);
    CHECK(r.status == RefStatus::Lost);
    CHECK(r.reason == "not_downstream");
  }
}

TEST_CASE("identity ops pass the entity on under their own node") {
  G g;
  const NodePtr a = g.add("a", "make_box_rsolid", {});
  // A tag node re-attributes the solid; the next op's witness names the face by the node that made it.
  const NodePtr t = g.add("t", "apply_tag_rselection", {a});
  const NodePtr b = g.add("b", "make_cut_rsolid", {t},
                          std::vector{entry(face("b", "face_3"), TopoEvent::Modified, {face("a", "face_5")})});
  const ResolvedRef r = resolve_by_history(b, kTop);
  CHECK(r.status == RefStatus::Ok);
  CHECK(ids(r) == std::vector<std::string>{"b:face_face_3"});
  CHECK(r.hops.front().untracked);

  // A selection names its sub-shapes by the source's topo ids; a fillet deletes the edge and generates its patch.
  Value edge_kind = Value::object();
  edge_kind.set("target_kind", "edge");
  const NodePtr s = g.add("s", "make_select_redge", {b}, std::nullopt, edge_kind);
  const ElementAnchor edge{"b", 0, Kind::Edge, "edge_edge_1"};
  const NodePtr f =
      g.add("f", "make_fillet_rsolid", {b, s},
            std::vector{entry(ref("s", Kind::Edge, "edge_edge_1"), TopoEvent::Deleted, {}),
                        entry(face("f", "face_8"), TopoEvent::Generated, {ref("s", Kind::Edge, "edge_edge_1")}),
                        entry(face("f", "face_2"), TopoEvent::Modified, {face("b", "face_3")})});
  CHECK(resolve_by_history(f, edge).reason == "deleted");
  CHECK(ids(resolve_by_history(f, edge, 0, FollowMode::Derived)) == std::vector<std::string>{"f:face_face_8"});
  // The face lineage is not diverted into the edge selection, and continues through the fillet.
  CHECK(ids(resolve_by_history(f, kTop)) == std::vector<std::string>{"f:face_face_2"});
}

TEST_CASE("only the branch that leads to the target is the reference's history") {
  G g;
  const NodePtr a = g.add("a", "make_box_rsolid", {});
  const NodePtr dead =
      g.add("x", "make_cut_rsolid", {a}, std::vector{entry(face("a", "face_5"), TopoEvent::Deleted, {})});
  const NodePtr live = g.add("y", "make_translate_rshape", {a},
                             std::vector{entry(face("y", "face_5"), TopoEvent::Modified, {face("a", "face_5")})});
  const NodePtr t = g.add("u", "make_union_rsolid", {dead, live},
                          std::vector{entry(face("u", "face_1"), TopoEvent::Modified, {face("y", "face_5")})});
  const ResolvedRef r = resolve_by_history(t, kTop);
  CHECK(r.status == RefStatus::Ok);
  CHECK(ids(r) == std::vector<std::string>{"u:face_face_1"});
  REQUIRE(r.hops.size() == 2);
  CHECK(r.hops[0].node_id == "y");
}

TEST_CASE("the feature of a node id is its namespace") {
  CHECK(node_feature("cellA_node_0000002a") == "cellA");
  CHECK(node_feature("my_cell_node_00000001") == "my_cell");
  CHECK(node_feature("node_00000001").empty());
  // A feature cell's namespace is "<slug>.<code digest>": the feature is the slug, whatever the code.
  CHECK(node_feature("base.c1a2b3c4_node_00000001") == "base");
  CHECK(node_feature("base.c1a2b3c4_2_n_00000003") == "base");
  CHECK(node_feature("n_00000008").empty());
}

TEST_CASE("a stable anchor names the node by feature, op and occurrence upstream of it") {
  // Two runs of one cell: the second has a box inserted first and a translate before the cut.
  const auto run = [](bool insert) {
    auto g = std::make_unique<G>();
    std::vector<NodePtr> pre;
    Value small = Value::object();
    small.set("width", 4.0);
    if (insert)
      pre.push_back(g->add("c_node_00000001", "make_box_rsolid", {}, std::nullopt, small));
    const std::string box_id = insert ? "c_node_00000002" : "c_node_00000001";
    NodeSpec spec;
    spec.node_id = box_id;
    spec.op = "make_box_rsolid";
    spec.params = Value::object();
    spec.params.set("width", 40.0);
    TopoDelta delta;
    TopoRoleEntry top;
    top.ref = TopoRef{"g", box_id, 0, Kind::Face, "face_face_5"};
    top.role = "box.top";
    delta.roles.push_back(top);
    spec.topo_delta = delta;
    NodePtr body = g->graph.add_node(std::move(spec));
    if (insert)
      body =
          g->add("c_node_00000003", "make_translate_rshape", {body},
                 std::vector{entry(face("c_node_00000003", "face_5"), TopoEvent::Modified, {face(box_id, "face_5")})});
    std::vector<NodePtr> inputs{body};
    inputs.insert(inputs.end(), pre.begin(), pre.end());
    const std::string cut_id = insert ? "c_node_00000004" : "c_node_00000002";
    const std::string parent = insert ? "c_node_00000003" : box_id;
    const NodePtr cut =
        g->add(cut_id, "make_cut_rsolid", inputs,
               std::vector{entry(face(cut_id, "face_2"), TopoEvent::Modified, {face(parent, "face_5")})});
    return std::make_pair(std::move(g), cut);
  };
  const auto [g1, cut1] = run(false);
  const StableAnchor stable = stabilize(cut1, ElementAnchor{"c_node_00000001", 0, Kind::Face, "face_face_5"});
  CHECK(stable.node == StableNodeKey{"c", "make_box_rsolid", 0});
  CHECK(stable.role == "box.top");

  // The inserted box is not upstream of the plate's box node, so both boxes are occurrence 0; their parameters
  // tell them apart.
  const auto [g2, cut2] = run(true);
  const auto located = locate(cut2, stable);
  REQUIRE(located);
  CHECK(located->node_id == "c_node_00000002");
  const ResolvedRef r = resolve_by_history(cut2, *located);
  CHECK(r.status == RefStatus::Ok);
  CHECK(ids(r) == std::vector<std::string>{"c_node_00000004:face_face_2"});
  // The raw node id now names the inserted box.
  CHECK(cut2->inputs.back()->node_id == "c_node_00000001");
  CHECK(find_by_stable_key(cut2, stable.node).size() == 2);
  // The value form round-trips.
  CHECK(stable_anchor_from_value(to_value(stable)).node.params_digest == stable.node.params_digest);

  // Same key, same parameters: ambiguous, so nothing is located (never the first one).
  StableAnchor blind = stable;
  blind.node.params_digest = "0000000000000000";
  CHECK_FALSE(locate(cut2, blind));
}
