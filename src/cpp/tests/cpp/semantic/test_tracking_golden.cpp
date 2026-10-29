// The deltas tracked_* produce, held against the reference SDK.
//
// tracking_golden_record.py runs the same scenarios through Python's tracked_*
// functions and writes, per scenario, the event counts and -- for every entry,
// role, section edge and delta_entries record -- the centres of mass of the
// source and result shapes.  Centres, not kernel ids, so the comparison does
// not care how either side numbers its shapes.
#include "doctest.h"

#include <algorithm>
#include <sstream>
#include <string>
#include <vector>

#include "scad/core/vec.hpp"
#include "scad/kernel/booleans.hpp"
#include "scad/kernel/builders.hpp"
#include "scad/kernel/curves.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/semantic/tracking.hpp"
#include "test_tracking_support.hpp"
#include "tracking_golden.hpp"

using namespace scad;
using namespace scad::tracking_test;

namespace {

std::vector<std::string> golden(const std::string& name) {
  for (const auto& c : tracking_golden::kCases) {
    if (name != c.name)
      continue;
    std::vector<std::string> lines;
    std::istringstream in(c.text);
    for (std::string line; std::getline(in, line);) {
      if (!line.empty())
        lines.push_back(line);
    }
    std::sort(lines.begin() + 1, lines.end());  // line 0 is the counts
    return lines;
  }
  FAIL("no golden case " << name);
  return {};
}

std::string difference(const std::vector<std::string>& expected, const std::vector<std::string>& actual) {
  std::string out;
  for (const std::string& line : expected) {
    if (std::find(actual.begin(), actual.end(), line) == actual.end())
      out += "\n  missing   " + line;
  }
  for (const std::string& line : actual) {
    if (std::find(expected.begin(), expected.end(), line) == expected.end())
      out += "\n  unexpected " + line;
  }
  return out;
}

void expect_golden(const char* name, const TrackedResult& tracked, const std::vector<TopoDS_Shape>& inputs) {
  const auto expected = golden(name);
  const auto actual = summarise(tracked.delta, tracked.delta_entries, inputs, tracked.shape.wrapped());
  CHECK_MESSAGE(expected == actual, name << difference(expected, actual));
}

void expect_golden(const char* name, const TrackedBooleanResult& tracked, const std::vector<TopoDS_Shape>& inputs) {
  REQUIRE(tracked.solid.has_value());
  const auto expected = golden(name);
  const auto actual = summarise(tracked.delta, tracked.delta_entries, inputs, tracked.solid->wrapped());
  CHECK_MESSAGE(expected == actual, name << difference(expected, actual));
}

const Solid& unit_box() {
  static const Solid box = box_solid(10, 10, 10);
  return box;
}

std::vector<Edge> first_edges(const Solid& solid, std::size_t n) {
  std::vector<Edge> all = solid.edges();
  all.resize(n, all.front());
  return all;
}

}  // namespace

TEST_CASE("tracking vs reference: primitives name their own faces and edges") {
  expect_golden("box", tracked_box({0, 0, 0}, 2.0, 3.0, 4.0), {});
  expect_golden("cylinder", tracked_cylinder({0, 0, 0}, {0, 0, 1}, 2.0, 5.0), {});
  expect_golden("cone", tracked_cone({0, 0, 0}, {0, 0, 1}, 3.0, 1.0, 4.0), {});
  expect_golden("cone_point", tracked_cone({0, 0, 0}, {0, 0, 1}, 3.0, 0.0, 4.0), {});
}

TEST_CASE("tracking vs reference: rigid transforms move every face by continuation") {
  const Solid& box = unit_box();
  expect_golden("translate", tracked_translate(box, {5, 0, 0}), {box.wrapped()});
  expect_golden("rotate", tracked_rotate(box, 45.0, {0, 0, 1}), {box.wrapped()});
  expect_golden("mirror", tracked_mirror(box, {0, 0, 0}, {1, 0, 0}), {box.wrapped()});
}

TEST_CASE("tracking vs reference: extrude and revolve") {
  const Face rect = rectangle_face(5.0, 3.0);
  expect_golden("extrude_rect", tracked_extrude(rect, {0, 0, 1}, 10.0), {rect.wrapped()});
  const Face circle = circle_face({0, 0, 0}, 2.0);
  expect_golden("extrude_circle", tracked_extrude(circle, {0, 0, 1}, 3.0), {circle.wrapped()});

  const Face profile = rectangle_face(2.0, 1.0, {3, 0, 0});
  expect_golden("revolve", tracked_revolve(profile, {0, 1, 0}, {0, 0, 0}, 180.0), {profile.wrapped()});
  expect_golden("revolve_full", tracked_revolve(profile, {0, 1, 0}, {0, 0, 0}, 360.0), {profile.wrapped()});
}

TEST_CASE("tracking vs reference: fillet, chamfer, shell") {
  const Solid& box = unit_box();
  const std::vector<Edge> four = first_edges(box, 4);
  expect_golden("fillet4", tracked_fillet(box, four, 0.5), {box.wrapped()});
  expect_golden("chamfer4", tracked_chamfer(box, four, 0.5), {box.wrapped()});
  expect_golden("fillet_all", tracked_fillet(box, box.edges(), 1.0), {box.wrapped()});

  const std::vector<Face> faces = box.faces();
  const Face top = *std::max_element(faces.begin(), faces.end(),
                                     [](const Face& a, const Face& b) { return a.center().z < b.center().z; });
  expect_golden("shell", tracked_shell(box, {top}, 1.0), {box.wrapped()});
}

TEST_CASE("tracking vs reference: loft, sweep, twisted sweep") {
  const Wire first = rectangle_wire(2.0, 2.0);
  const Wire last = rectangle_wire(1.0, 1.0, {0, 0, 2});
  expect_golden("loft", tracked_loft({first, last}), {first.wrapped(), last.wrapped()});
  expect_golden("loft_ruled", tracked_loft({first, last}, true), {first.wrapped(), last.wrapped()});

  const Face square = rectangle_face(1.0, 1.0);
  const Wire path(kernel::make_polyline_wire({{0, 0, 0}, {0, 0, 3}}));
  expect_golden("sweep", tracked_sweep(square, path), {square.wrapped(), path.wrapped()});
  expect_golden("twisted_sweep", tracked_twisted_sweep(square, {0, 0, 1}, {0, 0, 0}, 3.0, 45.0, 0.5), {});
}

TEST_CASE("tracking vs reference: cut, union, intersect") {
  const Solid body = box_solid(10, 10, 10);
  const Solid tangent_tool = cylinder_solid(2.0, 15.0, {3, 3, -2.5});
  expect_golden("cut_tangent", tracked_cut(body, tangent_tool), {body.wrapped(), tangent_tool.wrapped()});

  const Solid blind = cylinder_solid(1.0, 6.0, {0, 0, 2});
  expect_golden("cut_blind_hole", tracked_cut(body, blind), {body.wrapped(), blind.wrapped()});

  const Solid union_tool = cylinder_solid(4.0, 10.0, {3, 3, 0});
  expect_golden("union", tracked_union(body, union_tool), {body.wrapped(), union_tool.wrapped()});

  const Solid common_tool = cylinder_solid(6.0, 10.0, {3, 3, 0});
  expect_golden("intersect", tracked_intersect(body, common_tool), {body.wrapped(), common_tool.wrapped()});
}

TEST_CASE("tracking vs reference: N-ary union history") {
  std::vector<Solid> row;
  std::vector<TopoDS_Shape> inputs;
  for (int i = 0; i < 3; ++i) {
    row.push_back(box_solid(1.0, 1.0, 1.0, {static_cast<double>(i), 0, 0}));
    inputs.push_back(row.back().wrapped());
  }
  for (const bool clean : {true, false}) {
    CAPTURE(clean);
    std::vector<TopoDS_Shape> shapes = inputs;
    const kernel::FuseHistoryResult fused = kernel::fuse_shapes_with_history(shapes, false, 1e-7, clean);
    const std::vector<TopoDS_Solid> solids = kernel::solids_of(fused.shape);
    REQUIRE(solids.size() == 1);
    const Solid result(solids.front());
    const TrackedBooleanResult tracked = track_union_history(row, result, *fused.history, fused.section_edges);
    expect_golden(clean ? "union3_clean" : "union3_raw", tracked, inputs);
  }
}

TEST_CASE("tracking vs reference: the graph policy keeps roles and section edges, drops history") {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  const Solid& box = unit_box();
  const Face rect = rectangle_face(5.0, 3.0);
  expect_golden("graph_extrude", tracked_extrude(rect, {0, 0, 1}, 10.0), {rect.wrapped()});
  expect_golden("graph_translate", tracked_translate(box, {5, 0, 0}), {box.wrapped()});
  expect_golden("graph_fillet", tracked_fillet(box, first_edges(box, 4), 0.5), {box.wrapped()});

  const Solid tool = cylinder_solid(2.0, 15.0, {3, 3, -2.5});
  expect_golden("graph_cut", tracked_cut(box_solid(10, 10, 10), tool), {box.wrapped(), tool.wrapped()});
}
