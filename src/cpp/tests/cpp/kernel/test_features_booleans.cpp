#include "doctest.h"

#include <BRepBuilderAPI_MakeVertex.hxx>
#include <TopoDS.hxx>
#include <gp_Pnt.hxx>

#include <cmath>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/kernel/booleans.hpp"
#include "scad/kernel/builders.hpp"
#include "scad/kernel/cast.hpp"
#include "scad/kernel/curves.hpp"
#include "scad/kernel/features.hpp"
#include "scad/kernel/membership.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"

using namespace scad;
using namespace scad::kernel;

namespace {

TopoDS_Wire rectangle(double w, double h, double z = 0.0) {
  return make_polyline_wire({{-w / 2, -h / 2, z}, {w / 2, -h / 2, z}, {w / 2, h / 2, z}, {-w / 2, h / 2, z}}, true);
}

TopoDS_Solid cube(double x, double size = 2.0) { return make_box_solid({x, 0, 0}, size, size, size); }

}  // namespace

// ---------------------------------------------------------------------------
// features
// ---------------------------------------------------------------------------

TEST_CASE("faces from wires, with and without holes") {
  const TopoDS_Face plain = make_face_from_wire(rectangle(3.0, 2.0));
  CHECK(surface_area(plain) == doctest::Approx(6.0));

  const TopoDS_Wire hole = make_wire_from_edges({make_circle_edge({0, 0, 0}, 0.5, {0, 0, 1})});
  const TopoDS_Face holed = make_face_from_wires(rectangle(3.0, 2.0), {hole});
  CHECK(surface_area(holed) == doctest::Approx(6.0 - kPi * 0.25));
  CHECK(inner_wires_of(holed).size() == 1);
}

TEST_CASE("loft: frustum volume, endpoints, and what it refuses") {
  const TopoDS_Shape frustum = make_loft_solid({rectangle(2.0, 2.0), rectangle(1.0, 1.0, 2.0)});
  CHECK(volume(frustum) == doctest::Approx(2.0 / 3.0 * (4.0 + 1.0 + 2.0)).epsilon(1e-6));
  CHECK(volume(make_loft_solid({rectangle(2.0, 2.0), rectangle(1.0, 1.0, 2.0)}, /*ruled=*/true)) ==
        doctest::Approx(14.0 / 3.0).epsilon(1e-6));

  const TopoDS_Vertex tip = BRepBuilderAPI_MakeVertex(gp_Pnt(0, 0, 3)).Vertex();
  CHECK(volume(make_loft_solid({rectangle(2.0, 2.0), tip})) == doctest::Approx(4.0).epsilon(1e-6));

  CHECK_THROWS_AS((void)make_loft_solid({rectangle(2.0, 2.0)}), ValueError);
  CHECK_THROWS_AS((void)make_loft_solid({rectangle(2.0, 2.0), make_face_from_wire(rectangle(1.0, 1.0, 2.0))}),
                  TypeError);
  CHECK_THROWS_AS((void)make_loft_solid({rectangle(2.0, 2.0), TopoDS_Shape()}), TypeError);
}

TEST_CASE("sweep a square along a segment") {
  const TopoDS_Wire path = make_polyline_wire({{0, 0, 0}, {0, 0, 3}});
  const TopoDS_Shape solid = make_sweep_solid(rectangle(1.0, 1.0), path);
  CHECK(volume(solid) == doctest::Approx(3.0).epsilon(1e-6));
  CHECK(solid.ShapeType() == TopAbs_SOLID);
  CHECK(volume(make_sweep_solid(rectangle(1.0, 1.0), path, /*is_frenet=*/true)) == doctest::Approx(3.0).epsilon(1e-6));
}

TEST_CASE("helical sweep: a small square wound around the axis") {
  // The profile is built about the axis and the builder moves it out to the helix radius.
  const TopoDS_Wire profile = make_polyline_wire(
      {{-0.1, 0, -0.1}, {0.1, 0, -0.1}, {0.1, 0, 0.1}, {-0.1, 0, 0.1}}, true);
  const TopoDS_Shape thread = make_helical_sweep_solid(profile, 1.0, 3.0, 1.0, {0, 0, 0}, {0, 0, 1});
  const double centreline = 3.0 * std::sqrt(4.0 * kPi * kPi + 1.0);
  CHECK(volume(thread) == doctest::Approx(0.04 * centreline).epsilon(0.02));  // Pappus, approximately
  CHECK(bounding_box(thread).zlen() == doctest::Approx(3.2).epsilon(0.02));
}

// ---------------------------------------------------------------------------
// booleans
// ---------------------------------------------------------------------------

TEST_CASE("cut, common and fuse volumes") {
  const TopoDS_Solid a = cube(0.0);
  const TopoDS_Solid b = cube(1.0);  // overlaps a by half
  CHECK(volume(cut_shapes(a, {b})) == doctest::Approx(4.0));
  CHECK(volume(common_shapes({a, b})) == doctest::Approx(4.0));
  CHECK(volume(fuse_shapes({a, b})) == doctest::Approx(12.0));

  CHECK(cut_shapes(a, {}).IsSame(a));
  CHECK(common_shapes({a}).IsSame(a));
  CHECK(fuse_shapes({a}).IsSame(a));
  CHECK_THROWS_AS((void)common_shapes({}), ValueError);
  CHECK_THROWS_AS((void)fuse_shapes({}), ValueError);

  // Three overlapping solids intersect left to right.
  CHECK(volume(common_shapes({a, b, cube(1.5)})) == doctest::Approx(2.0 * 2.0 * 0.5));
  // Several tools are cut in one pass.
  CHECK(volume(cut_shapes(cube(0.0, 4.0), {cube(0.0, 1.0), cube(2.0, 1.0)})) == doctest::Approx(64.0 - 2.0));
}

TEST_CASE("run_boolean keeps history on request") {
  const TopoDS_Solid a = cube(0.0);
  const TopoDS_Solid b = cube(1.0);

  const BooleanResult bare = run_boolean(BooleanOp::Fuse, a, {b});
  CHECK(bare.done);
  CHECK(bare.history.IsNull());
  CHECK(bare.section_edges.empty());

  BooleanOptions options;
  options.fill_history = true;
  const BooleanResult kept = run_boolean(BooleanOp::Cut, a, {b}, options);
  REQUIRE(kept.done);
  REQUIRE_FALSE(kept.history.IsNull());

  // A bore through the box meets two faces along a circle each.
  const TopoDS_Solid bore = make_cylinder_solid({1, 1, -1}, {0, 0, 1}, 0.5, 4.0);
  const BooleanResult drilled = run_boolean(BooleanOp::Cut, a, {bore}, options);
  REQUIRE(drilled.done);
  CHECK(drilled.section_edges.size() == 2);
  CHECK(run_boolean(BooleanOp::Cut, a, {bore}).section_edges.empty());  // no history asked, none kept

  SubShapeIndex in_result(kept.shape);
  int survived = 0, modified = 0;
  for (const TopoDS_Face& face : faces_of(a)) {
    if (!kept.history->Modified(face).IsEmpty()) ++modified;
    if (in_result.contains(face) && kept.history->Modified(face).IsEmpty()) ++survived;
  }
  CHECK(modified >= 1);
  CHECK(survived >= 1);
}

TEST_CASE("fuse with history: clean-up merges faces and the history follows it") {
  std::vector<TopoDS_Shape> row;
  for (int i = 0; i < 3; ++i) row.push_back(make_box_solid({static_cast<double>(i), 0, 0}, 1, 1, 1));

  const FuseHistoryResult raw = fuse_shapes_with_history(row, false, 1e-7, /*clean=*/false);
  CHECK(faces_of(raw.shape).size() == 14);
  const FuseHistoryResult clean = fuse_shapes_with_history(row, false, 1e-7, /*clean=*/true);
  CHECK(faces_of(clean.shape).size() == 6);
  CHECK(volume(clean.shape) == doctest::Approx(3.0));
  REQUIRE_FALSE(clean.history.IsNull());

  // Every face of the merged top is the descendant of the three input top faces.
  int descendants = 0;
  for (const TopoDS_Shape& input : row) {
    for (const TopoDS_Face& face : faces_of(input)) {
      if (clean.history->IsRemoved(face)) continue;
      if (!clean.history->Modified(face).IsEmpty()) ++descendants;
    }
  }
  CHECK(descendants > 0);

  // Section edges are kept only if they survive into the result.
  SubShapeIndex in_result(clean.shape);
  for (const TopoDS_Shape& edge : clean.section_edges) CHECK(in_result.contains(edge));
}

TEST_CASE("fuse_shapes_with_history edge cases") {
  const TopoDS_Solid a = cube(0.0);
  const FuseHistoryResult single = fuse_shapes_with_history({a});
  CHECK(single.shape.IsSame(a));
  CHECK_FALSE(single.history.IsNull());
  CHECK_THROWS_AS((void)fuse_shapes_with_history({}), ValueError);

  // Glue is a hint: for overlapping solids the unglued fuse takes over.
  const FuseHistoryResult glued = fuse_shapes_with_history({a, cube(1.0)}, /*glue=*/true);
  CHECK(solids_of(glued.shape).size() == 1);
  CHECK(volume(glued.shape) == doctest::Approx(12.0));
  CHECK(volume(fuse_shapes({a, cube(1.0)}, /*glue=*/true)) == doctest::Approx(12.0));
}

TEST_CASE("clean_shape unifies coplanar faces") {
  const TopoDS_Shape raw = fuse_shapes({make_box_solid({0, 0, 0}, 1, 1, 1), make_box_solid({1, 0, 0}, 1, 1, 1)}, false,
                                       std::nullopt, /*clean=*/false);
  CHECK(faces_of(raw).size() == 10);
  CHECK(faces_of(clean_shape(raw)).size() == 6);
}
