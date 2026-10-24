#include "doctest.h"

#include <BRepBuilderAPI_MakeVertex.hxx>
#include <gp_Pnt.hxx>

#include <cmath>
#include <optional>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/kernel/curves.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"

using namespace scad;
using namespace scad::kernel;

namespace {

double distance_to(const TopoDS_Shape& shape, const Vec3& point) {
  return distance(BRepBuilderAPI_MakeVertex(gp_Pnt(point.x, point.y, point.z)).Vertex(), shape);
}

}  // namespace

TEST_CASE("line edges") {
  CHECK(linear_length(make_line_edge({0, 0, 0}, {3, 4, 0})) == doctest::Approx(5.0));
  CHECK_THROWS_AS((void)make_line_edge({1, 1, 1}, {1, 1, 1}), KernelError);
}

TEST_CASE("circle edges: length, plane, and where the parametrisation starts") {
  const TopoDS_Edge circle = make_circle_edge({1, 0, 0}, 2.0, {0, 0, 1});
  CHECK(linear_length(circle) == doctest::Approx(4.0 * kPi));
  const BoundingBox bounds = bounding_box(circle);
  CHECK(bounds.zlen() == doctest::Approx(0.0).epsilon(1e-6));
  CHECK(bounds.xlen() == doctest::Approx(4.0).epsilon(1e-6));

  const TopoDS_Edge turned = make_circle_edge({0, 0, 0}, 1.0, {0, 0, 1}, Vec3{0, 1, 0});
  const Vec3 start = vertex_point(vertices_of(turned).front());
  CHECK(start.x == doctest::Approx(0.0).epsilon(1e-9));
  CHECK(start.y == doctest::Approx(1.0));
  CHECK_THROWS_AS((void)make_circle_edge({0, 0, 0}, -1.0, {0, 0, 1}), KernelError);
  CHECK_THROWS_AS((void)make_circle_edge({0, 0, 0}, 1.0, {0, 0, 0}), ValueError);
}

TEST_CASE("ellipse edges") {
  // The exact perimeter of a 2 x 1 ellipse is 9.688448; the Gauss integration of
  // BRepGProp::LinearProperties is good to a few parts in a thousand.
  const TopoDS_Edge ellipse = make_ellipse_edge({0, 0, 0}, 2.0, 1.0, {0, 0, 1});
  CHECK(linear_length(ellipse) == doctest::Approx(9.688448).epsilon(3e-3));
  CHECK_THROWS_AS((void)make_ellipse_edge({0, 0, 0}, 1.0, 2.0, {0, 0, 1}), ValueError);
  CHECK_THROWS_AS((void)make_ellipse_edge({0, 0, 0}, 0.0, 0.0, {0, 0, 1}), ValueError);
  const BoundingBox along_y = bounding_box(make_ellipse_edge({0, 0, 0}, 2.0, 1.0, {0, 0, 1}, Vec3{0, 1, 0}));
  CHECK(along_y.ylen() == doctest::Approx(4.0).epsilon(1e-6));
}

TEST_CASE("arcs through three points and by angle") {
  const TopoDS_Edge half = make_arc_three_point_edge({1, 0, 0}, {0, 1, 0}, {-1, 0, 0});
  CHECK(linear_length(half) == doctest::Approx(kPi));
  CHECK(distance_to(half, {0, 1, 0}) == doctest::Approx(0.0).epsilon(1e-9));
  CHECK_THROWS_AS((void)make_arc_three_point_edge({0, 0, 0}, {1, 0, 0}, {2, 0, 0}), KernelError);

  const TopoDS_Edge quarter = make_arc_angle_edge({0, 0, 0}, 2.0, 0.0, kPi / 2.0, {0, 0, 1});
  CHECK(linear_length(quarter) == doctest::Approx(kPi));
  const std::vector<TopoDS_Vertex> ends = vertices_of(quarter);
  REQUIRE(ends.size() == 2);
  CHECK(vertex_point(ends[0]).x == doctest::Approx(2.0));
  CHECK(vertex_point(ends[1]).y == doctest::Approx(2.0));

  // Seen from -Z the same angles run the other way round.
  const TopoDS_Edge flipped = make_arc_angle_edge({0, 0, 0}, 2.0, 0.0, kPi / 2.0, {0, 0, -1}, Vec3{1, 0, 0});
  CHECK(vertex_point(vertices_of(flipped)[1]).y == doctest::Approx(-2.0));
}

TEST_CASE("B-spline edges: explicit definition and interpolation") {
  BSplineSpec spec;
  spec.control_points = {{0, 0, 0}, {3, 0, 0}, {3, 4, 0}};
  spec.degree = 1;
  spec.knots = {0.0, 1.0, 2.0};
  spec.multiplicities = {2, 1, 2};
  CHECK(linear_length(make_bspline_edge(spec)) == doctest::Approx(7.0));
  spec.weights = {1.0, 1.0, 1.0};
  CHECK(linear_length(make_bspline_edge(spec)) == doctest::Approx(7.0));

  BSplineSpec bad = spec;
  bad.multiplicities = {1, 1, 1};  // not clamped: too few knots for the poles
  CHECK_THROWS_AS((void)make_bspline_edge(bad), KernelError);

  const std::vector<Vec3> points{{0, 0, 0}, {1, 1, 0}, {2, 0, 0}, {3, 1, 0}};
  const TopoDS_Edge through = make_interpolated_bspline_edge(points);
  for (const Vec3& p : points) CHECK(distance_to(through, p) < 1e-6);
  CHECK_THROWS(make_interpolated_bspline_edge({{0, 0, 0}}));
}

TEST_CASE("wires from edges and from points") {
  const TopoDS_Wire open = make_polyline_wire({{0, 0, 0}, {1, 0, 0}, {1, 1, 0}});
  CHECK(edges_of(open).size() == 2);
  CHECK_FALSE(is_wire_closed(open));
  const TopoDS_Wire closed = make_polyline_wire({{0, 0, 0}, {1, 0, 0}, {1, 1, 0}}, true);
  CHECK(edges_of(closed).size() == 3);
  CHECK(is_wire_closed(closed));
  CHECK(linear_length(closed) == doctest::Approx(2.0 + std::sqrt(2.0)));

  // Two points make one segment: there is nothing to close.
  CHECK(edges_of(make_polyline_wire({{0, 0, 0}, {1, 0, 0}}, true)).size() == 1);

  CHECK_THROWS_AS((void)make_wire_from_edges({make_line_edge({0, 0, 0}, {1, 0, 0}), make_line_edge({5, 5, 5}, {6, 5, 5})}),
                  KernelError);
  CHECK_THROWS_AS((void)make_polyline_wire({}), KernelError);
}

TEST_CASE("helix: length, rise, handedness") {
  const double pitch = 2.0, radius = 1.0;
  const TopoDS_Wire helix = make_helix_wire(pitch, 6.0, radius, {0, 0, 0}, {0, 0, 1});
  const double turn = std::sqrt((2.0 * kPi * radius) * (2.0 * kPi * radius) + pitch * pitch);
  CHECK(linear_length(helix) == doctest::Approx(3.0 * turn).epsilon(1e-5));
  CHECK(bounding_box(helix).zlen() == doctest::Approx(6.0).epsilon(1e-6));

  // A quarter turn up: a right-handed helix has turned toward +Y, a left-handed one toward -Y.
  const auto end_of = [&](std::string_view handedness) {
    const TopoDS_Wire w = make_helix_wire(pitch, pitch / 4.0, radius, {0, 0, 0}, {0, 0, 1}, std::nullopt, handedness);
    return vertex_point(vertices_of(w).back());
  };
  CHECK(end_of("Right").y == doctest::Approx(1.0).epsilon(1e-6));
  CHECK(end_of("Left").y == doctest::Approx(-1.0).epsilon(1e-6));

  CHECK_THROWS_WITH((void)make_helix_wire(pitch, 1.0, radius, {0, 0, 0}, {0, 0, 1}, std::nullopt, "Sideways"),
                    "handedness must be 'Right' or 'Left'");
  CHECK_THROWS_AS((void)make_helix_wire(0.0, 1.0, radius, {0, 0, 0}, {0, 0, 1}), ValueError);
}
