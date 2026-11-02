// fillet_corner_rsketch and chamfer_corner_rsketch: the corner geometry, the constraints that define it, the refusals.
#include "doctest.h"

#include <algorithm>
#include <cmath>
#include <functional>
#include <string>
#include <utility>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/sketch/operators.hpp"

using namespace scad;

namespace {

SketchPoint2 xy_of(const Sketch& s, const std::string& id) {
  const SketchEntity& point = s.entities().at(id);
  return {point.number("x"), point.number("y")};
}

bool near(const SketchPoint2& p, double x, double y) {
  return std::hypot(p.first - x, p.second - y) < 1e-6;
}

bool has(const std::vector<std::string>& ids, const std::string& id) {
  return std::find(ids.begin(), ids.end(), id) != ids.end();
}

// A 10 x 6 rectangle anchored at a, with horizontal / vertical lines and the two length dimensions.
Sketch rectangle(bool dimensions = true) {
  Sketch s = make_sketch_rsketch("corner");
  s = add_point_rsketch(s, "a", 0, 0);
  s = add_point_rsketch(s, "b", 10, 0);
  s = add_point_rsketch(s, "c", 10, 6);
  s = add_point_rsketch(s, "d", 0, 6);
  s = add_line_rsketch(s, "l0", "a", "b");
  s = add_line_rsketch(s, "l1", "b", "c");
  s = add_line_rsketch(s, "l2", "c", "d");
  s = add_line_rsketch(s, "l3", "d", "a");
  s = constrain_fix_rsketch(s, "a");
  s = constrain_horizontal_rsketch(s, "l0");
  s = constrain_horizontal_rsketch(s, "l2");
  s = constrain_vertical_rsketch(s, "l1");
  s = constrain_vertical_rsketch(s, "l3");
  if (dimensions) {
    s = constrain_length_rsketch(s, "l0", 10.0);
    s = constrain_length_rsketch(s, "l1", 6.0);
  }
  return s;
}

std::string failure_text(const std::function<void()>& call) {
  try {
    call();
  } catch (const Error& e) {
    return e.guidance().technical_details;
  }
  return {};
}

}  // namespace

TEST_CASE("fillet: a right-angle corner gets a quarter arc tangent to both lines, counter-clockwise") {
  const Sketch before = rectangle();
  const Sketch after = fillet_corner_rsketch(before, "l0", "l1", 2.0);
  const SketchDiff diff = diff_sketch_rsketchdiff(before, after);
  CHECK(diff.created == std::vector<std::string>{"p1", "p2", "p3", "a1"});
  CHECK(has(diff.removed, "b"));  // the corner nothing uses any more
  CHECK(has(diff.changed, "l0"));
  CHECK(has(diff.changed, "l1"));

  const SketchEntity& arc = after.entities().at("a1");
  CHECK(arc.kind == "arc");
  CHECK(near(xy_of(after, arc.point_id("start")), 8.0, 0.0));
  CHECK(near(xy_of(after, arc.point_id("end")), 10.0, 2.0));
  CHECK(near(xy_of(after, arc.point_id("center")), 8.0, 2.0));
  CHECK(after.entities().at("l0").point_id("end") == arc.point_id("start"));
  CHECK(after.entities().at("l1").point_id("start") == arc.point_id("end"));

  std::vector<std::string> kinds;
  for (const SketchConstraint& constraint : after.constraints())
    kinds.push_back(constraint.kind);
  CHECK(std::count(kinds.begin(), kinds.end(), "tangent") == 2);
  CHECK(std::count(kinds.begin(), kinds.end(), "radius") == 1);
  CHECK(std::count(kinds.begin(), kinds.end(), "horizontal") == 2);  // l0 and l2 keep theirs
  CHECK(std::count(kinds.begin(), kinds.end(), "length") == 0);      // the dimensions no longer hold
  CHECK(diff.removed_constraints.size() == 2);
}

TEST_CASE("fillet: the arc survives a re-solve and the sketch still promotes to a closed wire") {
  Sketch after = fillet_corner_rsketch(rectangle(), "l0", "l1", 2.0);
  const SketchSolveResult solved = after.solve(SketchSolveRequest{});
  CHECK(solved.status != "conflicting");
  CHECK(solved.status != "failed");
  CHECK(solved.dof == 2);  // the two lengths that were dropped
  CHECK(solved.solved_points.at("p1").first == doctest::Approx(8.0).epsilon(1e-6));
  CHECK(solved.solved_scalars.at("arc:a1:radius") == doctest::Approx(2.0).epsilon(1e-6));
  const Wire wire = make_wire_from_sketch_rwire(after);
  CHECK(wire.is_closed());
  CHECK(wire.edges().size() == 5);
}

TEST_CASE("fillet: an oblique corner puts the tangent points at r / tan(angle / 2) from the corner") {
  Sketch s = make_sketch_rsketch("oblique");
  s = add_point_rsketch(s, "a", 0, 0);
  s = add_point_rsketch(s, "b", 10, 0);
  s = add_point_rsketch(s, "c", 10 + 10 * std::cos(2.0 * kPi / 3.0), 10 * std::sin(2.0 * kPi / 3.0));
  s = add_line_rsketch(s, "l0", "a", "b");
  s = add_line_rsketch(s, "l1", "b", "c");  // 60 degrees between the lines at b
  const Sketch after = fillet_corner_rsketch(s, "l0", "l1", 1.0);
  const double reach = 1.0 / std::tan(kPi / 6.0);  // r / tan(30 deg)
  const SketchEntity& arc = after.entities().at("a1");
  const SketchPoint2 start = xy_of(after, arc.point_id("start"));
  const SketchPoint2 end = xy_of(after, arc.point_id("end"));
  CHECK(std::hypot(start.first - 10.0, start.second) == doctest::Approx(reach).epsilon(1e-9));
  CHECK(std::hypot(end.first - 10.0, end.second) == doctest::Approx(reach).epsilon(1e-9));
  const SketchPoint2 center = xy_of(after, arc.point_id("center"));
  CHECK(std::hypot(center.first - start.first, center.second - start.second) == doctest::Approx(1.0).epsilon(1e-9));
  CHECK(std::hypot(center.first - end.first, center.second - end.second) == doctest::Approx(1.0).epsilon(1e-9));
}

TEST_CASE("fillet: a corner point that constraints use stays, with the cut-off legs as construction lines") {
  Sketch s = constrain_distance_rsketch(rectangle(), "b", "d", std::hypot(10.0, 6.0), "diag");
  const Sketch after = fillet_corner_rsketch(s, "l0", "l1", 2.0);
  CHECK(after.entities().contains("b"));
  std::vector<std::string> legs;
  for (const auto& [id, entity] : after.entities())
    if (entity.kind == "line" && entity.construction)
      legs.push_back(id);
  CHECK(legs.size() == 2);
  const SketchSolveResult solved = Sketch(after).solve(SketchSolveRequest{});
  CHECK(solved.dof == 1);  // the two lengths are gone, the diagonal dimension remains
  CHECK(solved.solved_points.at("b").first == doctest::Approx(10.0).epsilon(1e-6));
}

TEST_CASE("fillet: refuses parallel lines, lines without a shared point, bad radii, and names the maximum") {
  Sketch s = make_sketch_rsketch("refuse");
  s = add_point_rsketch(s, "a", 0, 0);
  s = add_point_rsketch(s, "b", 10, 0);
  s = add_point_rsketch(s, "c", 10, 6);
  s = add_point_rsketch(s, "d", 20, 0);
  s = add_line_rsketch(s, "h", "a", "b");
  s = add_line_rsketch(s, "v", "b", "c");
  s = add_line_rsketch(s, "w", "b", "d");
  s = add_line_rsketch(s, "z", "c", "d");
  CHECK_THROWS_AS(fillet_corner_rsketch(s, "h", "w", 1.0), Error);
  CHECK(failure_text([&] { fillet_corner_rsketch(s, "h", "w", 1.0); }).find("parallel") != std::string::npos);
  CHECK(failure_text([&] { fillet_corner_rsketch(s, "h", "z", 1.0); }).find("do not share an end point") !=
        std::string::npos);
  CHECK(failure_text([&] { fillet_corner_rsketch(s, "h", "v", 0.0); }).find("greater than zero") != std::string::npos);
  CHECK(failure_text([&] { fillet_corner_rsketch(s, "h", "v", 7.0); }).find("at most 6") != std::string::npos);
  CHECK(failure_text([&] { fillet_corner_rsketch(s, "h", "h", 1.0); }).find("two different lines") !=
        std::string::npos);
  CHECK(failure_text([&] { fillet_corner_rsketch(s, "h", "nope", 1.0); }).find("'nope'") != std::string::npos);
  s = add_circle_rsketch(s, "k", "a", 1.0);
  CHECK(failure_text([&] { fillet_corner_rsketch(s, "h", "k", 1.0); }).find("is a circle") != std::string::npos);
}

TEST_CASE("fillet: the input sketch is not changed and the result is the same every time") {
  const Sketch before = rectangle();
  const Value once = fillet_corner_rsketch(before, "l0", "l1", 2.0).to_value();
  CHECK(before.entities().contains("b"));
  CHECK(before.entities().size() == 8);
  CHECK(fillet_corner_rsketch(before, "l0", "l1", 2.0).to_value() == once);
}

TEST_CASE("chamfer: a straight cut at the distance along each line, defined by a length and an angle") {
  const Sketch after = chamfer_corner_rsketch(rectangle(), "l0", "l1", 2.0);
  const SketchEntity& cut = after.entities().at("l4");
  CHECK(near(xy_of(after, cut.point_id("start")), 8.0, 0.0));
  CHECK(near(xy_of(after, cut.point_id("end")), 10.0, 2.0));
  CHECK(after.entities().at("l0").point_id("end") == cut.point_id("start"));
  CHECK(!after.entities().contains("b"));
  std::vector<std::string> kinds;
  for (const SketchConstraint& constraint : after.constraints())
    kinds.push_back(constraint.kind);
  CHECK(std::count(kinds.begin(), kinds.end(), "angle") == 1);
  CHECK(std::count(kinds.begin(), kinds.end(), "length") == 1);  // the chamfer's; the lines' were dropped
  Sketch copy = after;
  const SketchSolveResult solved = copy.solve(SketchSolveRequest{});
  CHECK(solved.status != "conflicting");
  CHECK(solved.solved_points.at(cut.point_id("end")).second == doctest::Approx(2.0).epsilon(1e-6));
  CHECK(failure_text([&] { chamfer_corner_rsketch(rectangle(), "l0", "l1", 6.0); }).find("less than 6") !=
        std::string::npos);
  CHECK(failure_text([&] { chamfer_corner_rsketch(rectangle(), "l0", "l1", -1.0); }).find("greater than zero") !=
        std::string::npos);
}
