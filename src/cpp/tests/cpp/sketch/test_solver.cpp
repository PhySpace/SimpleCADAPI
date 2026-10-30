// Solver behaviour through the functional API; the cases port the solver parts of
// test_sketch_api.py, test_sketch_histcad_constraints.py, test_sketch_ellipse.py
// and test_error_diagnostics_sketch.py, with positions cross-checked against py-slvs.
#include "doctest.h"

#include <cmath>
#include <string>

#include "scad/core/error.hpp"
#include "scad/sketch/operators.hpp"

using namespace scad;

namespace {

Sketch with_points(Sketch s, std::initializer_list<std::pair<const char*, std::pair<double, double>>> points) {
  for (const auto& [id, xy] : points)
    s = add_point_rsketch(s, id, xy.first, xy.second);
  return s;
}

SketchSolveResult inspect(const Sketch& s, bool strict = true, bool fully = false) {
  return inspect_sketch_rsketchresult(s, {.require_fully_constrained = fully, .strict = strict});
}

SketchPoint2 at(const SketchSolveResult& r, const char* id) {
  return r.solved_points.at(id);
}

Sketch constrained_rectangle() {
  Sketch s = make_sketch_rsketch("rect");
  s = with_points(s, {{"p0", {0, 0}}, {"p1", {2, 0}}, {"p2", {2, 1}}, {"p3", {0, 1}}});
  s = add_line_rsketch(s, "bottom", "p0", "p1");
  s = add_line_rsketch(s, "right", "p1", "p2");
  s = add_line_rsketch(s, "top", "p2", "p3");
  s = add_line_rsketch(s, "left", "p3", "p0");
  s = constrain_horizontal_rsketch(s, "bottom");
  s = constrain_vertical_rsketch(s, "right");
  s = constrain_parallel_rsketch(s, "bottom", "top");
  s = constrain_parallel_rsketch(s, "left", "right");
  s = constrain_perpendicular_rsketch(s, "bottom", "right");
  s = constrain_equal_length_rsketch(s, "bottom", "top");
  s = constrain_equal_length_rsketch(s, "left", "right");
  s = constrain_distance_rsketch(s, "p0", "p1", 2.0);
  s = constrain_distance_rsketch(s, "p0", "p3", 1.0);
  s = constrain_fix_rsketch(s, "p0");
  return s;
}

}  // namespace

TEST_CASE("a redundantly constrained rectangle is solved with zero DOF and status code 5") {
  const SketchSolveResult r = inspect(constrained_rectangle(), true, true);
  CHECK(r.status == "solved");
  CHECK(r.dof == 0);
  CHECK(r.residual_norm == doctest::Approx(0.0).epsilon(1e-7));
  CHECK(r.backend == "scad-native");
  CHECK(r.backend_status_code == 5);
  CHECK(at(r, "p2").first == doctest::Approx(2.0));
  CHECK(at(r, "p2").second == doctest::Approx(1.0));
}

TEST_CASE("a free line has four degrees of freedom") {
  Sketch s = with_points(make_sketch_rsketch("open"), {{"p0", {0, 0}}, {"p1", {1, 0}}});
  s = add_line_rsketch(s, "line", "p0", "p1");
  const SketchSolveResult r = inspect(s, false);
  CHECK(r.status == "underconstrained");
  CHECK(r.dof == 4);
}

TEST_CASE("circle radius and center constraints solve to zero DOF") {
  Sketch s = with_points(make_sketch_rsketch("circle"), {{"center", {0, 0}}});
  s = add_circle_rsketch(s, "outer", "center", 1.5);
  s = constrain_fix_rsketch(s, "center");
  s = constrain_radius_rsketch(s, get_sketch_entity_rsketchref(s, "outer"), 1.5);
  const SketchSolveResult r = inspect(s, true, true);
  CHECK(r.status == "solved");
  CHECK(r.solved_scalars.at("circle:outer:radius") == doctest::Approx(1.5));
}

TEST_CASE("conflicting distances name the later constraint and revert the geometry") {
  Sketch s = with_points(make_sketch_rsketch("conflict fixture"), {{"p1", {0, 0}}, {"p2", {10, 0}}});
  s = add_line_rsketch(s, "l1", "p1", "p2");
  s = constrain_distance_rsketch(s, "p1", "p2", 20.0, "c_far");
  s = constrain_distance_rsketch(s, "p1", "p2", 5.0, "c_near");
  const SketchSolveResult r = inspect(s, false);
  CHECK(r.status == "conflicting");
  CHECK(r.backend_status_code == 2 - 1);
  REQUIRE(r.diagnostics.size() == 1);
  CHECK(r.diagnostics[0].constraint_id == "c_near");
  CHECK(r.diagnostics[0].code == "residual_too_large");
  CHECK(at(r, "p2").first == doctest::Approx(10.0));

  try {
    (void)inspect(s);
    FAIL("a conflicting sketch must raise");
  } catch (const Error& e) {
    CHECK(e.operation() == "sketch_solve");
    bool near_miss = false;
    for (const auto& entry : e.guidance().inventory) {
      if (entry.symbol == "c_far" && entry.status == "near miss")
        near_miss = true;
      if (entry.symbol == "c_near")
        CHECK(entry.status == "failed");
    }
    CHECK(near_miss);
    const std::string text = e.what();
    CHECK(text.find("distance(p1, p2 = 5)") != std::string::npos);
  }
}

TEST_CASE("later conflicting constraints are named in order (probe: A=5, B=20, C=7)") {
  Sketch s = with_points(make_sketch_rsketch("abc"), {{"p1", {0, 0}}, {"p2", {10, 0}}});
  s = constrain_distance_rsketch(s, "p1", "p2", 5.0, "A");
  s = constrain_distance_rsketch(s, "p1", "p2", 20.0, "B");
  s = constrain_distance_rsketch(s, "p1", "p2", 7.0, "C");
  const SketchSolveResult r = inspect(s, false);
  REQUIRE(r.diagnostics.size() == 2);
  CHECK(r.diagnostics[0].constraint_id == "B");
  CHECK(r.diagnostics[1].constraint_id == "C");
}

TEST_CASE("an impossible triangle is a non-converging full-rank system: failed, both named") {
  Sketch s = with_points(make_sketch_rsketch("tri"), {{"a", {0, 0}}, {"b", {3, 0}}, {"c", {1, 2}}});
  s = constrain_fix_rsketch(s, "a", "fa");
  s = constrain_fix_rsketch(s, "b", "fb");
  s = constrain_distance_rsketch(s, "a", "c", 4.0, "ac");
  s = constrain_distance_rsketch(s, "b", "c", 10.0, "bc");
  const SketchSolveResult r = inspect(s, false);
  CHECK(r.status == "failed");
  CHECK(r.backend_status_code == 2);
  REQUIRE(r.diagnostics.size() == 2);
  CHECK(r.diagnostics[0].code == "did_not_converge");
}

TEST_CASE("an over-constrained rectangle width blames only the last dependent dimension") {
  Sketch s = make_sketch_rsketch("rect_over");
  s = with_points(s, {{"p0", {0, 0}}, {"p1", {2, 0}}, {"p2", {2, 1}}, {"p3", {0, 1}}});
  s = add_line_rsketch(s, "bottom", "p0", "p1");
  s = add_line_rsketch(s, "right", "p1", "p2");
  s = add_line_rsketch(s, "top", "p2", "p3");
  s = add_line_rsketch(s, "left", "p3", "p0");
  s = constrain_horizontal_rsketch(s, "bottom", "hb");
  s = constrain_horizontal_rsketch(s, "top", "ht");
  s = constrain_vertical_rsketch(s, "right", "vr");
  s = constrain_vertical_rsketch(s, "left", "vl");
  s = constrain_fix_rsketch(s, "p0", "fx");
  s = constrain_distance_x_rsketch(s, "p0", "p1", 2.0, "w1");
  s = constrain_distance_x_rsketch(s, "p3", "p2", 3.0, "w2");
  s = constrain_length_rsketch(s, "bottom", 2.0, "L");
  const SketchSolveResult r = inspect(s, false);
  CHECK(r.status == "conflicting");
  REQUIRE(r.diagnostics.size() == 1);
  CHECK(r.diagnostics[0].constraint_id == "w2");
}

TEST_CASE("reference dimensions are measured, not driven") {
  Sketch s = with_points(make_sketch_rsketch("reference"), {{"a", {0, 0}}, {"b", {3, 4}}});
  s = constrain_fix_rsketch(s, "a");
  s = constrain_fix_rsketch(s, "b");
  s = constrain_distance_rsketch(s, "a", "b", 99.0, "measured", /*driving=*/false);
  const SketchSolveResult r = inspect(s, true, true);
  CHECK(r.status == "solved");
  CHECK(r.solved_scalars.at("constraint:measured:value") == doctest::Approx(5.0));
}

TEST_CASE("an arc with a radius and point-on constraint is not conflicting") {
  Sketch s = with_points(make_sketch_rsketch("arc_radius"), {{"start", {2, 0}}, {"end", {0, 2}}, {"center", {0, 0}}});
  s = add_arc_rsketch(s, "arc", "start", "end", "center");
  s = constrain_fix_rsketch(s, "center");
  s = constrain_radius_rsketch(s, "arc", 2.0);
  s = constrain_point_on_rsketch(s, "end", "arc");
  const SketchSolveResult r = inspect(s, false);
  CHECK(r.status != "conflicting");
  CHECK(std::hypot(at(r, "start").first, at(r, "start").second) == doctest::Approx(2.0));
  CHECK(r.solved_entities.at("arc").find("sweep")->as_double() == doctest::Approx(kPi / 2));
}

TEST_CASE("a driving arc length is rejected with the Python guidance") {
  Sketch s =
      with_points(make_sketch_rsketch("arc_driving_length"), {{"center", {0, 0}}, {"start", {1, 0}}, {"end", {0, 1}}});
  s = add_arc_rsketch(s, "arc", "start", "end", "center");
  s = constrain_length_rsketch(s, "arc", 2.0);
  try {
    (void)inspect(s);
    FAIL("expected a ValueError");
  } catch (const Error& e) {
    CHECK(std::string(e.what()).find("Driving length constraints are supported only for lines") != std::string::npos);
  }
}

TEST_CASE("the driving angle holds each directed branch") {
  for (const double directed : {30.0, 150.0, 200.0, 330.0}) {
    const double radians = directed * kPi / 180.0;
    Sketch s = make_sketch_rsketch("angle");
    s = with_points(s, {{"p0", {0, 0}},
                        {"p1", {4, 0}},
                        {"p2", {1, 1}},
                        {"p3", {1 + 3 * std::cos(radians), 1 + 3 * std::sin(radians)}}});
    s = add_line_rsketch(s, "a", "p0", "p1");
    s = add_line_rsketch(s, "b", "p2", "p3");
    for (const char* p : {"p0", "p1", "p2"})
      s = constrain_fix_rsketch(s, p);
    s = constrain_length_rsketch(s, "b", 3.0);
    s = constrain_angle_rsketch(s, "a", "b", directed);
    const SketchSolveResult r = inspect(s, true, true);
    CHECK(r.status == "solved");
    const double measured = std::fmod(
        std::atan2(at(r, "p3").second - at(r, "p2").second, at(r, "p3").first - at(r, "p2").first) * 180.0 / kPi +
            360.0,
        360.0);
    CHECK(measured == doctest::Approx(directed).epsilon(1e-7));
  }
}

TEST_CASE("a zero driving angle redirects to the parallel constraint") {
  Sketch s =
      with_points(make_sketch_rsketch("angle"), {{"p0", {0, 0}}, {"p1", {4, 0}}, {"p2", {1, 1}}, {"p3", {4, 1.1}}});
  s = add_line_rsketch(s, "a", "p0", "p1");
  s = add_line_rsketch(s, "b", "p2", "p3");
  s = constrain_angle_rsketch(s, "a", "b", 0.0);
  try {
    (void)inspect(s);
    FAIL("expected a ValueError");
  } catch (const Error& e) {
    CHECK(std::string(e.what()).find("parallel") != std::string::npos);
  }
}

TEST_CASE("line distance keeps the initial side") {
  for (const double offset : {2.1, -1.8}) {
    Sketch s = make_sketch_rsketch("offset");
    s = with_points(s, {{"b0", {0, 0}}, {"b1", {5, 0}}, {"a0", {1, offset}}, {"a1", {5, offset}}});
    s = add_line_rsketch(s, "base", "b0", "b1");
    s = add_line_rsketch(s, "offset", "a0", "a1");
    s = constrain_fix_rsketch(s, "b0");
    s = constrain_fix_rsketch(s, "b1");
    s = constrain_length_rsketch(s, "offset", 4.0);
    s = constrain_parallel_rsketch(s, "offset", "base");
    s = constrain_distance_x_rsketch(s, "b0", "a0", 1.0);
    s = constrain_line_distance_rsketch(s, "offset", "base", 2.5);
    const SketchSolveResult r = inspect(s, true, true);
    CHECK(at(r, "a0").second == doctest::Approx(offset > 0 ? 2.5 : -2.5));
    CHECK(at(r, "a1").second == doctest::Approx(offset > 0 ? 2.5 : -2.5));
  }
}

TEST_CASE("mirror snaps the image line about the axis, also with flipped endpoints") {
  for (const bool flipped : {false, true}) {
    Sketch s = with_points(make_sketch_rsketch("mirror"),
                           {{"a0", {0, 0}},
                            {"a1", {0, 4}},
                            {"m0", {1, 1}},
                            {"m1", {1, 3}},
                            {"n0", flipped ? std::make_pair(-1.1, 2.9) : std::make_pair(-1.25, 1.1)},
                            {"n1", flipped ? std::make_pair(-1.2, 1.15) : std::make_pair(-1.1, 2.85)}});
    s = add_line_rsketch(s, "axis", "a0", "a1");
    s = add_line_rsketch(s, "source", "m0", "m1");
    s = add_line_rsketch(s, "image", "n0", "n1");
    for (const char* p : {"a0", "a1", "m0", "m1"})
      s = constrain_fix_rsketch(s, p);
    s = constrain_mirror_rsketch(s, "image", "axis", "source");
    const SketchSolveResult r = inspect(s, false);
    CHECK(at(r, "n0").first == doctest::Approx(-1.0));
    CHECK(at(r, "n1").first == doctest::Approx(-1.0));
    CHECK(at(r, "n0").second == doctest::Approx(flipped ? 3.0 : 1.0));
    CHECK(at(r, "n1").second == doctest::Approx(flipped ? 1.0 : 3.0));
  }
}

TEST_CASE("symmetric about a diagonal axis") {
  Sketch s =
      with_points(make_sketch_rsketch("sym"), {{"a0", {0, 0}}, {"a1", {3, 3}}, {"p", {1, 3}}, {"q", {2.6, 1.2}}});
  s = add_line_rsketch(s, "axis", "a0", "a1");
  for (const char* p : {"a0", "a1", "p"})
    s = constrain_fix_rsketch(s, p);
  s = constrain_symmetric_rsketch(s, "q", "p", "axis");
  const SketchSolveResult r = inspect(s, false);
  CHECK(at(r, "q").first == doctest::Approx(3.0).epsilon(1e-6));
  CHECK(at(r, "q").second == doctest::Approx(1.0).epsilon(1e-6));
}

TEST_CASE("midpoint of two points; duplicate points are rejected") {
  Sketch s = with_points(make_sketch_rsketch("midpoint"), {{"a", {0, 0}}, {"b", {4, 2}}, {"m", {1.8, 0.9}}});
  s = constrain_fix_rsketch(s, "a");
  s = constrain_fix_rsketch(s, "b");
  s = constrain_midpoint_points_rsketch(s, "m", "a", "b");
  const SketchSolveResult r = inspect(s, true, true);
  CHECK(at(r, "m").first == doctest::Approx(2.0));
  CHECK(at(r, "m").second == doctest::Approx(1.0));

  Sketch bad = with_points(make_sketch_rsketch("midpoint"), {{"a", {0, 0}}, {"b", {4, 2}}});
  bad = constrain_midpoint_points_rsketch(bad, "a", "a", "b");
  CHECK_THROWS(inspect(bad));
}

TEST_CASE("normal puts the probe line through the circle center") {
  Sketch s = with_points(make_sketch_rsketch("normal"), {{"c", {0, 0}}, {"p0", {0.5, 0.5}}, {"p1", {2, 2.4}}});
  s = add_circle_rsketch(s, "circle", "c", 1.0);
  s = add_line_rsketch(s, "probe", "p0", "p1");
  s = constrain_fix_rsketch(s, "c");
  s = constrain_radius_rsketch(s, "circle", 1.0);
  s = constrain_fix_rsketch(s, "p0");
  s = constrain_length_rsketch(s, "probe", 3.0);
  s = constrain_normal_rsketch(s, "probe", "circle");
  const SketchSolveResult r = inspect(s, true, true);
  const SketchPoint2 p0 = at(r, "p0");
  const SketchPoint2 p1 = at(r, "p1");
  CHECK(p0.first * p1.second - p0.second * p1.first == doctest::Approx(0.0).epsilon(1e-7));
}

TEST_CASE("circle-circle tangency, external and internal, is fully constrained") {
  for (const auto& [mode, distance] : {std::pair<const char*, double>{"external", 3.0}, {"internal", 1.0}}) {
    Sketch s = with_points(make_sketch_rsketch("tangent"), {{"a", {0, 0}}, {"b", {distance, 0}}});
    s = add_circle_rsketch(s, "left", "a", 2.0);
    s = add_circle_rsketch(s, "right", "b", 1.0);
    s = constrain_fix_rsketch(s, "left");
    s = constrain_fix_rsketch(s, "right");
    s = constrain_tangent_rsketch(s, "left", "right", std::nullopt, std::nullopt, mode, "tangent");
    CHECK(inspect(s, true, true).status == "solved");
  }
}

TEST_CASE("a tangent U path with arcs solves to zero DOF") {
  const double length = 80, height = 20, radius = 17;
  const double xl = -length / 2, xr = length / 2;
  Sketch s = make_sketch_rsketch("u_path");
  s = with_points(s, {{"lt", {xl, height}},
                      {"l1", {xl, radius}},
                      {"cl", {xl + radius, radius}},
                      {"b1", {xl + radius, 0}},
                      {"b2", {xr - radius, 0}},
                      {"cr", {xr - radius, radius}},
                      {"r1", {xr, radius}},
                      {"rt", {xr, height}}});
  s = add_line_rsketch(s, "arm_l", "lt", "l1");
  s = add_arc_rsketch(s, "corner_l", "l1", "b1", "cl");
  s = add_line_rsketch(s, "bottom", "b1", "b2");
  s = add_arc_rsketch(s, "corner_r", "b2", "r1", "cr");
  s = add_line_rsketch(s, "arm_r", "r1", "rt");
  s = constrain_fix_rsketch(s, "b1");
  s = constrain_vertical_rsketch(s, "arm_l");
  s = constrain_vertical_rsketch(s, "arm_r");
  s = constrain_horizontal_rsketch(s, "bottom");
  s = constrain_tangent_rsketch(s, "arm_l", "corner_l", std::nullopt, "start");
  s = constrain_tangent_rsketch(s, "corner_l", "bottom", "end");
  s = constrain_tangent_rsketch(s, "bottom", "corner_r", std::nullopt, "start");
  s = constrain_tangent_rsketch(s, "corner_r", "arm_r", "end");
  s = constrain_equal_radius_rsketch(s, "corner_l", "corner_r");
  s = constrain_radius_rsketch(s, "corner_l", radius);
  s = constrain_distance_x_rsketch(s, "lt", "rt", length);
  s = constrain_distance_y_rsketch(s, "b1", "lt", height);
  s = constrain_distance_y_rsketch(s, "b1", "rt", height);
  const SketchSolveResult r = inspect(s, true, true);
  CHECK(r.status == "solved");
  CHECK(r.dof == 0);
}

TEST_CASE("ellipse radii drive the axis points; orientation stays free") {
  const double theta = 30.0 * kPi / 180.0;
  Sketch s = make_sketch_rsketch("oval");
  s = with_points(s, {{"c", {0, 0}},
                      {"M", {4 * std::cos(theta), 4 * std::sin(theta)}},
                      {"m", {-2 * std::sin(theta), 2 * std::cos(theta)}}});
  s = add_ellipse_rsketch(s, "oval", "c", "M", "m");
  const SketchSolveResult plain = inspect(s, false);
  CHECK(plain.solved_entities.at("oval").find("angle")->as_double() == doctest::Approx(30.0));
  s = constrain_fix_rsketch(s, "c");
  s = constrain_major_radius_rsketch(s, "oval", 4.0);
  s = constrain_minor_radius_rsketch(s, "oval", 2.0);
  const SketchSolveResult r = inspect(s);
  CHECK(r.status == "underconstrained");
  CHECK(r.solved_entities.at("oval").find("major_radius")->as_double() == doctest::Approx(4.0));
  CHECK(r.solved_entities.at("oval").find("minor_radius")->as_double() == doctest::Approx(2.0));
}

TEST_CASE("tangent with an ellipse reports the unsupported kind") {
  Sketch s = with_points(make_sketch_rsketch("t"),
                         {{"c", {0, 0}}, {"M", {4, 0}}, {"m", {0, 2}}, {"p0", {5, 0}}, {"p1", {8, 0}}});
  s = add_ellipse_rsketch(s, "oval", "c", "M", "m");
  s = add_line_rsketch(s, "tan_line", "p0", "p1");
  s = constrain_tangent_rsketch(s, "tan_line", "oval");
  try {
    (void)inspect(s);
    FAIL("expected an error");
  } catch (const Error& e) {
    CHECK(std::string(e.what()).find("ellipse") != std::string::npos);
  }
}

TEST_CASE("B-spline solved entities and reference lengths") {
  Sketch s = with_points(make_sketch_rsketch("spline_measure"), {{"a", {0, 0}}, {"b", {3, 0}}});
  s = add_bspline_rsketch(s, "curve", "a", "b",
                          {SketchControlPoint(0.0, 0.0), SketchControlPoint(1.0, 1.0), SketchControlPoint(2.0, 1.0),
                           SketchControlPoint(3.0, 0.0)},
                          3, std::vector<Scalar>{0.0, 1.0}, std::vector<int>{4, 4});
  s = constrain_fix_rsketch(s, "curve");
  s = constrain_length_rsketch(s, "curve", 0.0, "curve_length", /*driving=*/false);
  const SketchSolveResult r = inspect(s, true, true);
  CHECK(r.solved_scalars.at("constraint:curve_length:value") > 3.0);
  CHECK(r.solved_entities.at("curve").find("solver_representation")->as_string() == "cubic_bezier");
}

TEST_CASE("an underconstrained requirement lists the unreferenced entities and the remaining DOF") {
  Sketch s = with_points(make_sketch_rsketch("loose fixture"), {{"a", {0, 0}}, {"b", {8, 0}}});
  s = add_line_rsketch(s, "seg", "a", "b");
  try {
    (void)inspect(s, true, true);
    FAIL("a loose sketch cannot be required to be fully constrained");
  } catch (const Error& e) {
    CHECK(e.operation() == "sketch_solve");
    const std::string text = e.what();
    CHECK(text.find("remaining DOF: 4") != std::string::npos);
    for (const char* symbol : {"- a [unconstrained]", "- b [unconstrained]", "- seg [unconstrained]"}) {
      CHECK(text.find(symbol) != std::string::npos);
    }
    CHECK(text.find("constrain_fix_rsketch") != std::string::npos);
  }
}

TEST_CASE("an empty sketch and a constraint-free sketch solve trivially") {
  CHECK(inspect(make_sketch_rsketch("empty"), false).status == "solved");
  const SketchSolveResult free_point = inspect(with_points(make_sketch_rsketch("one"), {{"p", {1, 2}}}), false);
  CHECK(free_point.dof == 2);
  CHECK(at(free_point, "p").first == 1.0);
}

TEST_CASE("a perturbed start stays in the basin of the initial geometry") {
  const double radians = 207.0 * kPi / 180.0;
  Sketch s = make_sketch_rsketch("angle");
  s = with_points(
      s,
      {{"p0", {0, 0}}, {"p1", {4, 0}}, {"p2", {1, 1}}, {"p3", {1 + 3 * std::cos(radians), 1 + 3 * std::sin(radians)}}});
  s = add_line_rsketch(s, "a", "p0", "p1");
  s = add_line_rsketch(s, "b", "p2", "p3");
  for (const char* p : {"p0", "p1", "p2"})
    s = constrain_fix_rsketch(s, p);
  s = constrain_length_rsketch(s, "b", 3.0);
  s = constrain_angle_rsketch(s, "a", "b", 200.0);
  const SketchSolveResult r = inspect(s);
  const double measured =
      std::fmod(std::atan2(at(r, "p3").second - 1.0, at(r, "p3").first - 1.0) * 180.0 / kPi + 360.0, 360.0);
  CHECK(measured == doctest::Approx(200.0).epsilon(1e-7));
}

TEST_CASE("solving is deterministic and honours the tolerance option") {
  const Sketch s = constrained_rectangle();
  const SketchSolveResult a = inspect(s, true, true);
  const SketchSolveResult b = inspect(s, true, true);
  CHECK(a.to_value() == b.to_value());
  const SketchSolveResult loose = inspect_sketch_rsketchresult(s, {.tolerance = 1e-3});
  CHECK(loose.status == "solved");
}

namespace {
// A scalar whose value can change after the sketch was made: stands in for a reactive Var.
struct MutableNode final : ExprNode {
  explicit MutableNode(double v) : value(v) {}
  double eval(const Bindings*) const override { return value; }
  std::string repr() const override { return "mutable"; }
  mutable double value;
};
}  // namespace

TEST_CASE("symbolic coordinates are re-evaluated on every solve") {
  const auto node = std::make_shared<MutableNode>(3.0);
  Sketch s = make_sketch_rsketch("symbolic");
  s = add_point_rsketch(s, "p", Scalar(ExprPtr(node)), 1.0);
  CHECK(at(inspect(s, false), "p").first == 3.0);
  node->value = 7.5;
  CHECK(at(inspect(s, false), "p").first == 7.5);
}

TEST_CASE("a fixed circle keeps its radius; circle radius is a DOF otherwise") {
  Sketch s = with_points(make_sketch_rsketch("circle"), {{"c", {0, 0}}});
  s = add_circle_rsketch(s, "k", "c", 2.0);
  CHECK(inspect(s, false).dof == 3);
  s = constrain_fix_rsketch(s, "k");
  const SketchSolveResult r = inspect(s, false);
  CHECK(r.dof == 0);
  CHECK(r.solved_scalars.at("circle:k:radius") == 2.0);
}
