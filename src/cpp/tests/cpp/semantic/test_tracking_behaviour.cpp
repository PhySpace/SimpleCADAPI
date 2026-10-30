// tracked_*: behaviours the reference comparison does not cover -- identity,
// record layout, policy, failure modes and the edge cases of each function.
#include "doctest.h"

#include <BRepBuilderAPI_MakeVertex.hxx>
#include <TopoDS.hxx>
#include <gp_Pnt.hxx>

#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/kernel/booleans.hpp"
#include "scad/kernel/builders.hpp"
#include "scad/kernel/cast.hpp"
#include "scad/kernel/curves.hpp"
#include "scad/kernel/features.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/semantic/tracking.hpp"
#include "test_tracking_support.hpp"

using namespace scad;
using namespace scad::tracking_test;

namespace {

std::set<std::string> ids_of(const std::vector<TopoRef>& refs) {
  std::set<std::string> ids;
  for (const TopoRef& r : refs)
    ids.insert(r.topo_id);
  return ids;
}

template <class Handles>
std::set<std::string> kernel_ids(const Handles& handles) {
  std::set<std::string> ids;
  for (const auto& h : handles)
    ids.insert(kernel_topo_id(h.wrapped()));
  return ids;
}

std::size_t count_role(const TopoDelta& delta, std::string_view role) {
  return static_cast<std::size_t>(
      std::count_if(delta.roles.begin(), delta.roles.end(), [&](const TopoRoleEntry& r) { return r.role == role; }));
}

// The ring: a disc of radius 2 with a concentric hole of radius 1.
Face ring_face() {
  const TopoDS_Wire outer = kernel::make_wire_from_edges({kernel::make_circle_edge({0, 0, 0}, 2.0, {0, 0, 1})});
  const TopoDS_Wire inner = kernel::make_wire_from_edges({kernel::make_circle_edge({0, 0, 0}, 1.0, {0, 0, 1})});
  return Face(kernel::make_face_from_wires(outer, {inner}));
}

}  // namespace

// ---------------------------------------------------------------------------
// identity
// ---------------------------------------------------------------------------

TEST_CASE("kernel ids follow the sub-shape, not the occurrence") {
  const Solid box = box_solid(10, 10, 10);
  const std::vector<Face> faces = box.faces();
  const TopoDS_Shape face = faces.front().wrapped();

  CHECK(kernel_topo_id(face) == kernel_topo_id(face.Reversed()));
  CHECK(kernel_topo_id(face) == kernel_topo_id(box.faces().front().wrapped()));
  CHECK(kernel_ids(faces).size() == 6);
  CHECK_FALSE(kernel_topo_id(face).empty());
  CHECK(kernel_topo_id(face) != kernel_topo_id(box.wrapped()));
}

TEST_CASE("every ref of an operation carries one temporary graph/node pair") {
  const TrackedResult first = tracked_translate(box_solid(10, 10, 10), {1, 0, 0});
  const TrackedResult second = tracked_translate(box_solid(10, 10, 10), {1, 0, 0});
  REQUIRE_FALSE(first.delta.entries.empty());

  const TopoRef& anchor = first.delta.entries.front().ref;
  CHECK(is_temporary_tracking_ref(anchor));
  CHECK(anchor.graph_id.size() == 10);  // "g_" + 8 hex digits
  CHECK(anchor.node_id.size() == 10);
  for (const TopoEntry& entry : first.delta.entries) {
    CHECK(entry.ref.graph_id == anchor.graph_id);
    CHECK(entry.ref.node_id == anchor.node_id);
    CHECK(entry.parent_refs.front().graph_id == anchor.graph_id);
    CHECK(entry.ref.output_slot == 0);
  }
  CHECK(anchor.node_id != second.delta.entries.front().ref.node_id);
  CHECK_FALSE(is_temporary_tracking_ref(TopoRef{}));
}

// ---------------------------------------------------------------------------
// record layout (what the tag projection reads)
// ---------------------------------------------------------------------------

TEST_CASE("a translate entry and its delta_entries record have the Python layout") {
  const Solid box = box_solid(10, 10, 10);
  const TrackedResult tracked = tracked_translate(box, {5, 0, 0});
  REQUIRE(tracked.delta.entries.size() == 6);
  CHECK(tracked.delta.modified.size() == 6);
  CHECK(tracked.delta_entries.size() == 6);

  const TopoEntry& entry = tracked.delta.entries.front();
  const std::string out_id = entry.ref.topo_id;
  const std::string in_id = entry.parent_refs.front().topo_id;
  CHECK(entry.event == TopoEvent::Modified);
  CHECK(entry.origin_role == std::optional<std::string>("body"));
  CHECK(entry.ref.kind == Kind::Face);
  CHECK(entry.parent_refs.front().kind == Kind::Face);
  CHECK(entry.metadata.dump() == R"({"derivation":"continuation","coverage":"complete","status":"proven",)"
                                 R"("evidence_kind":"kernel_history","source_kind":"FACE"})");

  const std::string witness = R"({"topo_id":")" + out_id +
                              R"(","event":"modified","kind":"FACE","source_kind":"FACE","origin_role":"body",)"
                              R"("input_topo_id":")" +
                              in_id + R"(","derivation":"continuation","coverage":"complete","status":"proven"})";
  CHECK(tracked.delta_entries.at(out_id).dump() ==
        R"({"topo_id":")" + out_id + R"(","kind":"FACE","event":"modified","origin_role":"body","input_topo_id":")" +
            in_id + R"(","derivation":"continuation","coverage":"complete","status":"proven","witnesses":[)" + witness +
            R"(],"events":["modified"],"origin_roles":["body"]})");

  // The ids name the real sub-shapes: the source is a face of the box, the result a face of the shape returned.
  CHECK(kernel_ids(box.faces()).contains(in_id));
  CHECK(kernel_ids(tracked.shape.as<Solid>().faces()).contains(out_id));
}

TEST_CASE("an extrusion's side face has a history witness and a role witness under one id") {
  const Face profile = rectangle_face(5.0, 3.0);
  const TrackedResult tracked = tracked_extrude(profile, {0, 0, 1}, 10.0);
  const Solid solid = tracked.shape.as<Solid>();
  CHECK(solid.volume() == doctest::Approx(150.0));

  REQUIRE(tracked.delta.generated.size() == 4);
  const std::set<std::string> side_ids = ids_of(tracked.delta.generated);
  const std::set<std::string> edge_ids = kernel_ids(profile.edges());
  for (const TopoRoleEntry& role : tracked.delta.roles) {
    if (role.role != "extrusion.side")
      continue;
    CHECK(side_ids.contains(role.ref.topo_id));
    REQUIRE(role.parent_refs.size() == 1);
    CHECK(role.parent_refs.front().kind == Kind::Edge);
    CHECK(edge_ids.contains(role.parent_refs.front().topo_id));
    CHECK(role.origin_role == std::optional<std::string>("profile"));
    CHECK(role.metadata.dump() == R"({"coverage":"complete","status":"proven","evidence_kind":"kernel_operation_role",)"
                                  R"("evidence_method":"Generated","source_kind":"EDGE"})");
  }

  const std::string id = tracked.delta.generated.front().topo_id;
  const Value& record = tracked.delta_entries.at(id);
  CHECK(record.find("witnesses")->size() == 2);
  CHECK(join(record.find("result_roles")) == "extrusion.side");
  const Value& history_witness = record.find("witnesses")->as_array()[0];
  CHECK(history_witness.find("result_role")->as_string() == "extrusion.side");
  CHECK(history_witness.find("project_source_tags")->as_bool());
  const Value& role_witness = record.find("witnesses")->as_array()[1];
  CHECK(role_witness.find("evidence_kind")->as_string() == "kernel_operation_role");
  CHECK(role_witness.find("evidence_method")->as_string() == "Generated");

  // The caps carry roles only, so their records have no history summary.
  const TopoRoleEntry* start = nullptr;
  for (const TopoRoleEntry& role : tracked.delta.roles) {
    if (role.role == "extrusion.start")
      start = &role;
  }
  REQUIRE(start != nullptr);
  CHECK(start->parent_refs.empty());
  const Value& cap = tracked.delta_entries.at(start->ref.topo_id);
  CHECK(cap.find("event")->is_null());
  CHECK(cap.find("derivation")->as_string() == "unknown");
  CHECK(cap.find("events") == nullptr);
  CHECK(join(cap.find("result_roles")) == "extrusion.start");
}

TEST_CASE("roles of the same fact are reported once") {
  // A cylinder's seam edge is one edge; naming it twice must not duplicate the role.
  const TrackedResult tracked = tracked_cylinder({0, 0, 0}, {0, 0, 1}, 2.0, 5.0);
  CHECK(tracked.delta.roles.size() == 6);
  std::set<std::pair<std::string, std::string>> distinct;
  for (const TopoRoleEntry& r : tracked.delta.roles)
    distinct.insert({r.role, r.ref.topo_id});
  CHECK(distinct.size() == 6);
}

// ---------------------------------------------------------------------------
// primitives
// ---------------------------------------------------------------------------

TEST_CASE("tracked_box places the box in a given frame") {
  const kernel::Axes3 turned{{0, 1, 0}, {-1, 0, 0}, {0, 0, 1}};  // x -> +Y
  const TrackedResult tracked = tracked_box({10, 0, 0}, 2.0, 3.0, 4.0, turned);
  const Solid box = tracked.shape.as<Solid>();
  CHECK(box.volume() == doctest::Approx(24.0));
  const kernel::BoundingBox bounds = box.bounding_box();
  CHECK(bounds.xmin == doctest::Approx(7.0));  // width along +Y, height along -X from the corner
  CHECK(bounds.xmax == doctest::Approx(10.0));
  CHECK(bounds.ymax == doctest::Approx(2.0));
  CHECK(tracked.delta.roles.size() == 6);
  CHECK(tracked.delta.entries.empty());
  CHECK(kernel_ids(box.faces()).size() == 6);
}

TEST_CASE("primitive roles name faces of the result") {
  for (const TrackedResult& tracked :
       {tracked_box({0, 0, 0}, 1, 2, 3), tracked_cylinder({0, 0, 0}, {1, 0, 0}, 1.0, 2.0),
        tracked_cone({0, 0, 0}, {0, 1, 0}, 2.0, 1.0, 3.0)}) {
    const Solid solid = tracked.shape.as<Solid>();
    const std::set<std::string> faces = kernel_ids(solid.faces());
    const std::set<std::string> edges = kernel_ids(solid.edges());
    for (const TopoRoleEntry& role : tracked.delta.roles) {
      const auto& universe = role.ref.kind == Kind::Face ? faces : edges;
      CHECK(universe.contains(role.ref.topo_id));
    }
  }
}

TEST_CASE("a degenerate primitive fails the way the kernel does") {
  CHECK_THROWS_AS((void)tracked_box({0, 0, 0}, 0.0, 1.0, 1.0), KernelError);
  CHECK_THROWS_AS((void)tracked_cylinder({0, 0, 0}, {0, 0, 0}, 1.0, 1.0), ValueError);
}

// ---------------------------------------------------------------------------
// policy
// ---------------------------------------------------------------------------

TEST_CASE("the graph policy changes what is recorded, never what is built") {
  const Face profile = rectangle_face(5.0, 3.0);
  const TrackedResult full = tracked_extrude(profile, {0, 0, 1}, 10.0);
  TrackedResult graph = [&] {
    const TrackingPolicyScope scope(TrackingPolicy::Graph);
    return tracked_extrude(profile, {0, 0, 1}, 10.0);
  }();
  CHECK(graph.shape.as<Solid>().volume() == doctest::Approx(full.shape.as<Solid>().volume()));
  CHECK(graph.delta.entries.empty());
  CHECK(graph.delta.generated.empty());
  CHECK(graph.delta.roles.size() == 2);  // the caps survive: they cost nothing
  CHECK(graph.delta_entries.size() == 2);
  CHECK(full.delta.roles.size() == 6);

  CHECK(current_tracking_policy() == TrackingPolicy::Full);  // the scope has ended
}

// ---------------------------------------------------------------------------
// transforms
// ---------------------------------------------------------------------------

TEST_CASE("transforms keep volume and move the box") {
  const Solid box = box_solid(10, 10, 10);
  const Solid moved = tracked_translate(box, {5, 0, 0}).shape.as<Solid>();
  CHECK(moved.volume() == doctest::Approx(1000.0));
  CHECK(moved.bounding_box().xmin == doctest::Approx(0.0));

  const Solid turned = tracked_rotate(box, 90.0, {0, 0, 1}, {0, 0, 0}).shape.as<Solid>();
  CHECK(turned.volume() == doctest::Approx(1000.0).epsilon(1e-6));

  const Solid mirrored = tracked_mirror(box, {0, 0, 0}, {1, 0, 0}).shape.as<Solid>();
  CHECK(mirrored.volume() == doctest::Approx(1000.0));
  CHECK(mirrored.faces().size() == 6);

  CHECK_THROWS_AS((void)tracked_rotate(box, 10.0, {0, 0, 0}, {0, 0, 0}), ValueError);
}

TEST_CASE("a transform leaves its input untouched") {
  const Solid box = box_solid(10, 10, 10);
  const std::set<std::string> before = kernel_ids(box.faces());
  const TrackedResult tracked = tracked_translate(box, {5, 0, 0});
  CHECK(kernel_ids(box.faces()) == before);
  for (const std::string& id : kernel_ids(tracked.shape.as<Solid>().faces()))
    CHECK_FALSE(before.contains(id));
}

// ---------------------------------------------------------------------------
// sweeps
// ---------------------------------------------------------------------------

TEST_CASE("extrude and revolve reject what they cannot build") {
  const Face profile = rectangle_face(5.0, 3.0);
  CHECK_THROWS_AS((void)tracked_extrude(profile, {0, 0, 0}, 10.0), ValueError);
  CHECK_THROWS_WITH((void)tracked_extrude(profile, {0, 0, 0}, 10.0), "Extrude direction cannot be zero-length");
  CHECK_THROWS_AS((void)tracked_revolve(profile, {0, 0, 0}, {0, 0, 0}, 90.0), ValueError);
}

TEST_CASE("an extrusion keeps the profile's holes as edges of the sides") {
  const Face ring = ring_face();
  const TrackedResult tracked = tracked_extrude(ring, {0, 0, 1}, 2.0);
  CHECK(tracked.shape.as<Solid>().volume() == doctest::Approx(3.0 * kPi * 2.0).epsilon(1e-6));
  CHECK(tracked.delta.generated.size() == 2);  // outer wall, bore
  CHECK(count_role(tracked.delta, "extrusion.side") == 2);
  CHECK(count_role(tracked.delta, "extrusion.start") == 1);
}

TEST_CASE("loft toward a point still finds its one cap") {
  const Wire base = rectangle_wire(2.0, 2.0);
  const Vertex tip(BRepBuilderAPI_MakeVertex(gp_Pnt(0, 0, 3)).Vertex());

  const TrackedResult up = tracked_loft({base, tip});
  CHECK(up.shape.as<Solid>().volume() == doctest::Approx(4.0));
  CHECK(count_role(up.delta, "loft.side") == 4);
  CHECK(count_role(up.delta, "loft.start") == 1);
  CHECK(count_role(up.delta, "loft.end") == 0);
  CHECK(up.delta.entries.size() == 4);

  const TrackedResult down = tracked_loft({tip, base});
  CHECK(count_role(down.delta, "loft.start") == 0);
  CHECK(count_role(down.delta, "loft.end") == 1);
}

TEST_CASE("loft takes only wires and vertices") {
  const Face face = rectangle_face(1.0, 1.0);
  const Wire wire = rectangle_wire(1.0, 1.0);
  CHECK_THROWS_AS((void)tracked_loft({wire, face}), TypeError);
  CHECK_THROWS_AS((void)tracked_loft({wire}), ValueError);  // one section is no loft (and crashes ThruSections)
}

TEST_CASE("sweep refuses a profile with holes") {
  const Wire path(kernel::make_polyline_wire({{0, 0, 0}, {0, 0, 3}}));
  CHECK_THROWS_AS((void)tracked_sweep(ring_face(), path), ValueError);
  const TrackedResult plain = tracked_sweep(rectangle_face(1.0, 1.0), path);
  CHECK(plain.shape.as<Solid>().volume() == doctest::Approx(3.0));
}

TEST_CASE("twisted sweep: annulus profile, argument checks, kernel metadata") {
  const TrackedResult ring = tracked_twisted_sweep(ring_face(), {0, 0, 1}, {0, 0, 0}, 3.0, 45.0, 0.5);
  const Solid solid = ring.shape.as<Solid>();
  CHECK(solid.volume() == doctest::Approx(3.0 * kPi * 3.0).epsilon(1e-4));
  CHECK(count_role(ring.delta, "twisted_sweep.side") == 2);
  CHECK(count_role(ring.delta, "twisted_sweep.start") == 1);
  CHECK(count_role(ring.delta, "twisted_sweep.end") == 1);
  CHECK(ring.delta.entries.empty());
  const Value meta = ring.shape.get_metadata("twisted_sweep.kernel");
  REQUIRE(meta.find("surface_error") != nullptr);
  CHECK(meta.find("surface_error")->as_double() >= 0.0);

  const Face square = rectangle_face(1.0, 1.0);
  CHECK_THROWS_WITH((void)tracked_twisted_sweep(square, {1, 0, 0}, {0, 0, 0}, 3.0, 45.0, 0.5),
                    "Twisted sweep profile must be normal to the sweep axis");
  CHECK_THROWS_WITH((void)tracked_twisted_sweep(square, {0, 0, 1}, {0, 0, 2}, 3.0, 45.0, 0.5),
                    "Twisted sweep profile must lie at the sweep origin");
}

// ---------------------------------------------------------------------------
// local features
// ---------------------------------------------------------------------------

TEST_CASE("fillet and chamfer: volumes, patches, and unreachable requests") {
  const Solid box = box_solid(10, 10, 10);
  const std::vector<Edge> edges = box.edges();
  const std::vector<Edge> four(edges.begin(), edges.begin() + 4);

  const TrackedResult fillet = tracked_fillet(box, four, 0.5);
  CHECK(fillet.shape.as<Solid>().volume() < 1000.0);
  CHECK(count_role(fillet.delta, "fillet.patch") == 4);
  CHECK(fillet.delta.deleted.size() == 4);  // the four filleted edges are gone

  const TrackedResult chamfer = tracked_chamfer(box, four, 0.5);
  CHECK(count_role(chamfer.delta, "chamfer.patch") == 4);
  CHECK(chamfer.shape.as<Solid>().volume() < 1000.0);

  CHECK_THROWS_AS((void)tracked_fillet(box, four, 100.0), Exception);
  CHECK_THROWS_AS((void)tracked_chamfer(box, four, 100.0), Exception);
}

TEST_CASE("an asymmetric chamfer puts the first distance on the given face") {
  const Solid box = box_solid(10, 10, 10);
  const Edge edge = box.edges().front();
  const std::vector<Face> faces = edge.incident_faces();
  REQUIRE(faces.size() == 2);

  const TrackedResult asymmetric = tracked_chamfer(box, {edge}, 0.5, 1.0, {{faces[0], faces[1]}});
  CHECK(1000.0 - asymmetric.shape.as<Solid>().volume() == doctest::Approx(2.5).epsilon(1e-6));  // d1*d2*L/2
  CHECK_THROWS_WITH((void)tracked_chamfer(box, {edge}, 0.5, 1.0),
                    "An asymmetric chamfer requires one (face1, face2) pair per edge");
}

TEST_CASE("shell roles: body, offset, closing descendants and walls") {
  const Solid box = box_solid(10, 10, 10);
  std::vector<Face> faces = box.faces();
  const Face top = *std::max_element(faces.begin(), faces.end(),
                                     [](const Face& a, const Face& b) { return a.center().z < b.center().z; });
  const TrackedResult tracked = tracked_shell(box, {top}, 1.0);
  CHECK(tracked.shape.as<Solid>().volume() == doctest::Approx(1000.0 - 8.0 * 8.0 * 9.0));
  CHECK(count_role(tracked.delta, "shell.offset_face") == 5);
  CHECK(count_role(tracked.delta, "shell.closing_descendant") == 1);
  CHECK(count_role(tracked.delta, "shell.wall") == 4);
  CHECK(count_role(tracked.delta, "shell.body_face") == 0);  // every kept face was re-created
}

// ---------------------------------------------------------------------------
// booleans
// ---------------------------------------------------------------------------

TEST_CASE("a cut that removes everything has no solid, only deletions") {
  const Solid tiny = box_solid(2, 2, 2, {0, 0, 4});
  const Solid big = box_solid(10, 10, 10);
  const TrackedBooleanResult tracked = tracked_cut(tiny, big);
  CHECK_FALSE(tracked.solid.has_value());
  CHECK(tracked.delta.deleted.size() == 12);  // all six faces of each input
  std::map<std::string, int> by_role;
  for (const TopoEntry& entry : tracked.delta.entries) {
    CHECK(entry.event == TopoEvent::Deleted);
    ++by_role[*entry.origin_role];
  }
  CHECK(by_role == std::map<std::string, int>{{"body", 6}, {"tool", 6}});
}

TEST_CASE("the same boolean twice gives the same delta") {
  const Solid plate = box_solid(60, 40, 4);
  const Solid tool = cylinder_solid(2.0, 6.0, {-24.0, 0, -1});
  std::vector<std::string> first;
  for (int run = 0; run < 3; ++run) {
    const TrackedBooleanResult tracked = tracked_cut(plate, tool);
    REQUIRE(tracked.solid.has_value());
    const auto summary =
        summarise(tracked.delta, tracked.delta_entries, {plate.wrapped(), tool.wrapped()}, tracked.solid->wrapped());
    if (run == 0)
      first = summary;
    CHECK(summary == first);
  }
}

TEST_CASE("a union of separate solids is not one solid") {
  const Solid a = box_solid(2, 2, 2);
  const Solid b = box_solid(2, 2, 2, {10, 0, 0});
  CHECK_THROWS_WITH((void)tracked_union(a, b), "Boolean union did not produce exactly one solid");
  const kernel::FuseHistoryResult single = kernel::fuse_shapes_with_history({a.wrapped()});
  CHECK_THROWS_WITH((void)track_union_history({a}, a, *single.history),
                    "Union history tracking requires at least two solids");
}

TEST_CASE("union section edges are in the result and distinct") {
  const Solid a = box_solid(10, 10, 10);
  const Solid b = cylinder_solid(4.0, 10.0, {3, 3, 0});
  const TrackedBooleanResult tracked = tracked_union(a, b);
  REQUIRE(tracked.solid.has_value());
  CHECK(tracked.delta.section_edges.size() == 2);
  const std::set<std::string> edges = kernel_ids(tracked.solid->edges());
  for (const TopoRef& ref : tracked.delta.section_edges) {
    CHECK(ref.kind == Kind::Edge);
    CHECK(edges.contains(ref.topo_id));
  }
  CHECK(ids_of(tracked.delta.section_edges).size() == tracked.delta.section_edges.size());
}

TEST_CASE("an N-ary union labels its inputs body, tool, tool_2, ...") {
  std::vector<Solid> row;
  std::vector<TopoDS_Shape> shapes;
  for (int i = 0; i < 4; ++i) {
    row.push_back(box_solid(1, 1, 1, {static_cast<double>(i), 0, 0}));
    shapes.push_back(row.back().wrapped());
  }
  const kernel::FuseHistoryResult fused = kernel::fuse_shapes_with_history(shapes, false, 1e-7, true);
  const Solid result(kernel::as_solid(fused.shape));
  const TrackedBooleanResult tracked = track_union_history(row, result, *fused.history, fused.section_edges);

  std::set<std::string> roles;
  for (const TopoEntry& e : tracked.delta.entries)
    roles.insert(*e.origin_role);
  CHECK(roles == std::set<std::string>{"body", "tool", "tool_2", "tool_3"});
  CHECK(result.faces().size() == 6);
}

TEST_CASE("boolean intersection of disjoint solids leaves nothing") {
  const TrackedBooleanResult tracked = tracked_intersect(box_solid(2, 2, 2), box_solid(2, 2, 2, {10, 0, 0}));
  CHECK_FALSE(tracked.solid.has_value());
}
