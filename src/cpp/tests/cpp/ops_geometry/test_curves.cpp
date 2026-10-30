// Points, lines, segments, polylines, arcs, helices, wires from edges.
#include "support.hpp"

#include <BRepAdaptor_Curve.hxx>
#include <TopoDS.hxx>
#include <gp_Pnt.hxx>

#include "scad/kernel/properties.hpp"

using namespace scad;
using namespace scad::geometry_test;

TEST_CASE("make_point_rvertex and make_line_redge") {
  const Vertex point = make_point_rvertex(1, 2, 3);
  CHECK(point.coordinates() == Vec3{1, 2, 3});
  CHECK(point.get_metadata("track").find("op")->as_string() == "make_point_rvertex");

  const Edge line = make_line_redge(scalar3(0, 0, 0), scalar3(3, 4, 0), "axis");
  CHECK(line.length() == doctest::Approx(5.0));
  CHECK(has_tag(line, "axis.edge"));
  CHECK(make_segment_redge(scalar3(0, 0, 0), scalar3(1, 0, 0)).length() == doctest::Approx(1.0));

  const Wire segment = make_segment_rwire(scalar3(0, 0, 0), scalar3(0, 5, 0));
  CHECK(segment.edges().size() == 1);
  CHECK(segment.get_metadata("track").find("op")->as_string() == "make_segment_wire");

  const auto coincident = failure_of([] { make_line_redge(scalar3(1, 1, 1), scalar3(1, 1, 1)); });
  REQUIRE(coincident);
  CHECK(coincident->operation() == "make_line_redge");
}

TEST_CASE("points and lines are placed through the current coordinate system") {
  const Workplane plane({1, 2, 3}, {0, 0, 1}, {0, 1, 0});
  CoordinateSystemScope scope(plane.cs());
  CHECK(make_point_rvertex(1, 0, 0).coordinates().y == doctest::Approx(3.0));  // local x is world y
  const Edge line = make_line_redge(scalar3(0, 0, 0), scalar3(2, 0, 0));
  check_box(line, {1, 2, 3}, {1, 4, 3});
}

TEST_CASE("make_polyline_rwire") {
  const std::vector<Scalar3> square{scalar3(0, 0, 0), scalar3(1, 0, 0), scalar3(1, 1, 0), scalar3(0, 1, 0)};
  CHECK_FALSE(make_polyline_rwire(square).is_closed());
  CHECK(make_polyline_rwire(square, true).is_closed());
  CHECK(make_polyline_rwire(square).edges().size() == 3);
  CHECK(make_polyline_rwire(square, true).edges().size() == 4);
  // Two points never close.
  CHECK(make_polyline_rwire({square[0], square[1]}, true).edges().size() == 1);

  const auto too_few = failure_of([] { make_polyline_rwire({scalar3(0, 0, 0)}); });
  REQUIRE(too_few);
  CHECK(too_few->operation() == "make_polyline_rwire");
  CHECK(too_few->guidance().possible_causes.front() == "Fewer than two points were provided.");
}

TEST_CASE("three-point and angle arcs") {
  const Edge half = make_three_point_arc_redge(scalar3(0, 0, 0), scalar3(1, 1, 0), scalar3(2, 0, 0));
  CHECK(half.length() == doctest::Approx(kPi));
  CHECK(make_three_point_arc_rwire(scalar3(0, 0, 0), scalar3(1, 1, 0), scalar3(2, 0, 0)).edges().size() == 1);
  const auto collinear =
      failure_of([] { make_three_point_arc_redge(scalar3(0, 0, 0), scalar3(1, 0, 0), scalar3(2, 0, 0)); });
  REQUIRE(collinear);
  CHECK(collinear->operation() == "make_three_point_arc_redge");

  const Edge quarter = make_angle_arc_redge(scalar3(0, 0, 0), 2.0, 0.0, kPi / 2);
  CHECK(quarter.length() == doctest::Approx(kPi));
  check_box(quarter, {0, 0, 0}, {2, 2, 0}, 1e-6);
  CHECK(make_angle_arc_rwire(scalar3(0, 0, 0), 1.0, 0.0, 1.0).edges().size() == 1);
  CHECK(failure_of([] { make_angle_arc_redge(scalar3(0, 0, 0), -1.0, 0.0, 1.0); }));
  CHECK(failure_of([] { make_angle_arc_redge(scalar3(0, 0, 0), 1.0, 0.5, 0.5); }));
  // The failing edge names its own operation inside a wire maker, as Python does.
  CHECK(failure_of([] { make_angle_arc_rwire(scalar3(0, 0, 0), -1.0, 0.0, 1.0); })->operation() ==
        "make_angle_arc_redge");
}

namespace {

// Signed turns about +Z along an edge, sampled.
double turns_of(const Edge& edge) {
  BRepAdaptor_Curve curve(TopoDS::Edge(edge.wrapped()));
  double total = 0, previous = 0;
  for (int i = 0; i <= 400; ++i) {
    const gp_Pnt p = curve.Value(curve.FirstParameter() + (curve.LastParameter() - curve.FirstParameter()) * i / 400.0);
    const double angle = std::atan2(p.Y(), p.X());
    if (i > 0) {
      double delta = angle - previous;
      while (delta > kPi)
        delta -= 2 * kPi;
      while (delta < -kPi)
        delta += 2 * kPi;
      total += delta;
    }
    previous = angle;
  }
  return total / (2 * kPi);
}

}  // namespace

TEST_CASE("helices wind with their handedness") {
  const Edge right = make_helix_redge(2.0, 10.0, 3.0);
  const Edge left = make_helix_redge(2.0, 10.0, 3.0, scalar3(0, 0, 0), scalar3(0, 0, 1), "Left");
  CHECK(turns_of(right) == doctest::Approx(5.0).epsilon(1e-3));
  CHECK(turns_of(left) == doctest::Approx(-5.0).epsilon(1e-3));
  CHECK(right.length() == doctest::Approx(left.length()));

  // Unlike the Python SDK, the wire keeps the handedness too.
  CHECK(turns_of(make_helix_rwire(2.0, 10.0, 3.0, scalar3(0, 0, 0), scalar3(0, 0, 1), "Left").edges().front()) ==
        doctest::Approx(-5.0).epsilon(1e-3));

  CHECK(failure_of([] { make_helix_redge(-1.0, 3.0, 0.5); })->guidance().technical_details ==
        "ValueError: The pitch must be greater than zero");
  CHECK(failure_of([] { make_helix_redge(1.0, 3.0, 0.5, scalar3(0, 0, 0), scalar3(0, 0, 1), "wrong"); }));
}

TEST_CASE("make_wire_from_edges_rwire chains edges and carries identity tags") {
  const Edge a = make_line_redge(scalar3(0, 0, 0), scalar3(2, 0, 0), "a");
  const Edge b = make_line_redge(scalar3(2, 0, 0), scalar3(2, 2, 0), "b");
  const Wire wire = make_wire_from_edges_rwire({a, b}, "path");
  CHECK(wire.edges().size() == 2);
  CHECK(has_tag(wire, "path.wire"));
  CHECK(count_with_tag(wire.edges(), "a.edge") == 1);
  // (OpenCASCADE copies the second edge when it joins the first, so only `a` is still itself.)

  const auto empty = failure_of([] { make_wire_from_edges_rwire({}); });
  REQUIRE(empty);
  CHECK(empty->operation() == "make_wire_from_edges_rwire");
  const Edge far = make_line_redge(scalar3(9, 9, 0), scalar3(10, 9, 0));
  CHECK(failure_of([&] { make_wire_from_edges_rwire({a, far}); }));
}
