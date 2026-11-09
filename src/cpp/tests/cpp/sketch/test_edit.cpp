// trim_rsketch, extend_rsketch and diff_sketch_rsketchdiff: the geometry of the cuts, the id rules, the constraints.
#include "doctest.h"

#include <algorithm>
#include <cmath>
#include <string>
#include <utility>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/sketch/operators.hpp"

using namespace scad;

namespace {

Sketch with_points(std::vector<std::pair<std::string, SketchPoint2>> points) {
  Sketch s = make_sketch_rsketch("edit");
  for (const auto& [id, xy] : points)
    s = add_point_rsketch(s, id, xy.first, xy.second);
  return s;
}

SketchPoint2 xy_of(const Sketch& s, const std::string& id) {
  const SketchEntity& point = s.entities().at(id);
  return {point.number("x"), point.number("y")};
}

std::vector<std::string> ids_of(const Sketch& s, const std::string& kind) {
  std::vector<std::string> out;
  for (const auto& [id, entity] : s.entities())
    if (entity.kind == kind)
      out.push_back(id);
  return out;
}

bool near(const SketchPoint2& p, double x, double y) {
  return std::hypot(p.first - x, p.second - y) < 1e-6;
}

// x-extent of a line piece, ordered
std::pair<double, double> span(const Sketch& s, const std::string& line) {
  const SketchEntity& e = s.entities().at(line);
  const double a = xy_of(s, e.point_id("start")).first;
  const double b = xy_of(s, e.point_id("end")).first;
  return {std::min(a, b), std::max(a, b)};
}

bool has(const std::vector<std::string>& ids, const std::string& id) {
  return std::find(ids.begin(), ids.end(), id) != ids.end();
}

Sketch plus() {
  Sketch s = with_points({{"a", {0, 0}}, {"b", {10, 0}}, {"c", {5, -5}}, {"d", {5, 5}}});
  s = add_line_rsketch(s, "h", "a", "b");
  s = add_line_rsketch(s, "v", "c", "d");
  return constrain_horizontal_rsketch(s, "h", "k1");
}

}  // namespace

TEST_CASE("trim: line crossed by a line keeps the far side, ties the cut, keeps the horizontal") {
  const Sketch before = plus();
  const Sketch after = trim_rsketch(before, "h", SketchPosition(8.0, 0.0));
  const SketchDiff diff = diff_sketch_rsketchdiff(before, after);
  CHECK(has(diff.removed, "h"));
  CHECK(has(diff.removed, "b"));  // the end point nothing uses any more
  CHECK(diff.created == std::vector<std::string>{"p1", "l1"});
  CHECK(has(diff.removed_constraints, "k1"));
  CHECK(diff.created_constraints == std::vector<std::string>{"c_horizontal_0", "c_point_on_0"});  // k1 was explicit
  CHECK(span(after, "l1").first == doctest::Approx(0.0));
  CHECK(span(after, "l1").second == doctest::Approx(5.0));
  CHECK(near(xy_of(after, "p1"), 5.0, 0.0));
  const SketchConstraint& tie = after.constraints().back();
  CHECK(tie.kind == "point_on");
  CHECK(tie.targets[0].entity_id == "p1");
  CHECK(tie.targets[1].entity_id == "v");
  CHECK(tie.targets[1].kind == "line");
}

TEST_CASE("trim: the middle of a line leaves two pieces") {
  Sketch s = with_points({{"a", {0, 0}}, {"b", {10, 0}}, {"c", {3, -5}}, {"d", {3, 5}}, {"e", {7, -5}}, {"f", {7, 5}}});
  s = add_line_rsketch(s, "h", "a", "b");
  s = add_line_rsketch(s, "v1", "c", "d");
  s = add_line_rsketch(s, "v2", "e", "f");
  const Sketch after = trim_rsketch(s, "h", SketchPosition(5.0, 0.0));
  CHECK(ids_of(after, "line") == std::vector<std::string>{"l1", "l2", "v1", "v2"});
  CHECK(span(after, "l1").second == doctest::Approx(3.0));
  CHECK(span(after, "l2").first == doctest::Approx(7.0));
  CHECK(after.entities().at("l1").point_id("start") == "a");
  CHECK(after.entities().at("l2").point_id("end") == "b");
  // the pieces are in the place the removed line had, behind the new points
  CHECK(after.entities().item(6).first == "p1");
}

TEST_CASE("trim: nothing crossing removes the line whole; the click may be a point id") {
  Sketch s = with_points({{"a", {0, 0}}, {"b", {10, 0}}, {"m", {5, 1}}});
  s = add_line_rsketch(s, "h", "a", "b");
  const Sketch after = trim_rsketch(s, "h", SketchPosition("m"));
  CHECK(ids_of(after, "line").empty());
  CHECK(after.entities().contains("m"));
  const Value* edit = after.metadata().find("last_edit");
  REQUIRE(edit != nullptr);
  CHECK(edit->find("notes")->as_array().at(0).as_string() == "h had nothing crossing it: removed whole");
}

TEST_CASE("trim: a circle between two lines leaves the long arc, counter-clockwise") {
  Sketch s = with_points({{"o", {0, 0}}, {"a", {-5, 2}}, {"b", {5, 2}}});
  s = add_circle_rsketch(s, "c", "o", 4.0);
  s = add_line_rsketch(s, "l", "a", "b");
  const Sketch after = trim_rsketch(s, "c", SketchPosition(0.0, 4.0));
  REQUIRE(ids_of(after, "arc").size() == 1);
  CHECK(ids_of(after, "circle").empty());
  const SketchEntity& arc = after.entities().at(ids_of(after, "arc")[0]);
  CHECK(arc.point_id("center") == "o");
  const SketchPoint2 start = xy_of(after, arc.point_id("start"));
  const SketchPoint2 end = xy_of(after, arc.point_id("end"));
  CHECK(near(start, -std::sqrt(12.0), 2.0));
  CHECK(near(end, std::sqrt(12.0), 2.0));
  // both ends are tied to the line that cut them
  int ties = 0;
  for (const SketchConstraint& c : after.constraints())
    ties += c.kind == "point_on" && c.targets[1].entity_id == "l";
  CHECK(ties == 2);
}

TEST_CASE("trim: a circle crossed once is an error, a free circle goes whole") {
  Sketch s = with_points({{"o", {0, 0}}, {"a", {0, 4}}, {"b", {0, 9}}});
  s = add_circle_rsketch(s, "c", "o", 4.0);
  s = add_line_rsketch(s, "l", "a", "b");
  CHECK_THROWS_WITH_AS((void)trim_rsketch(s, "c", SketchPosition(4.0, 0.0)), doctest::Contains("'c' is crossed once"),
                       Error);
  Sketch free = add_circle_rsketch(with_points({{"o", {0, 0}}}), "c", "o", 4.0);
  CHECK(ids_of(trim_rsketch(free, "c", SketchPosition(4.0, 0.0)), "circle").empty());
}

TEST_CASE("trim: an arc keeps the far side of a crossing, circle-circle crossings, tangent circles") {
  Sketch arc = with_points({{"o", {0, 0}}, {"s", {4, 0}}, {"e", {-4, 0}}, {"p", {0, 1}}, {"q", {0, 6}}});
  arc = add_arc_rsketch(arc, "a", "s", "e", "o");
  arc = add_line_rsketch(arc, "l", "p", "q");
  const Sketch trimmed = trim_rsketch(arc, "a", SketchPosition(-2.0, 3.4));
  REQUIRE(ids_of(trimmed, "arc").size() == 1);
  const SketchEntity& piece = trimmed.entities().at(ids_of(trimmed, "arc")[0]);
  CHECK(near(xy_of(trimmed, piece.point_id("start")), 4.0, 0.0));
  CHECK(near(xy_of(trimmed, piece.point_id("end")), 0.0, 4.0));

  Sketch two = with_points({{"o", {0, 0}}, {"p", {6, 0}}});
  two = add_circle_rsketch(two, "c1", "o", 4.0);
  two = add_circle_rsketch(two, "c2", "p", 4.0);
  const Sketch lens = trim_rsketch(two, "c1", SketchPosition(4.0, 0.0));
  REQUIRE(ids_of(lens, "arc").size() == 1);
  const SketchEntity& kept = lens.entities().at(ids_of(lens, "arc")[0]);
  CHECK(xy_of(lens, kept.point_id("start")).first == doctest::Approx(3.0));

  // two circles that touch from outside meet in one point: a single cut, which a circle cannot be trimmed at
  Sketch touch = with_points({{"o", {0, 0}}, {"p", {8, 0}}});
  touch = add_circle_rsketch(touch, "c1", "o", 4.0);
  touch = add_circle_rsketch(touch, "c2", "p", 4.0);
  CHECK_THROWS_WITH_AS((void)trim_rsketch(touch, "c1", SketchPosition(-4.0, 0.0)), doctest::Contains("is crossed once"),
                       Error);
}

TEST_CASE("trim: tolerance - a crossing at an end is no cut, a point on the cut is reused") {
  Sketch s = with_points({{"a", {0, 0}},
                          {"b", {10, 0}},
                          {"c", {10, -5}},
                          {"d", {10, 5}},
                          {"e", {4, -5}},
                          {"f", {4, 5}},
                          {"near", {4.0, 5e-8}}});
  s = add_line_rsketch(s, "h", "a", "b");
  s = add_line_rsketch(s, "touch", "c", "d");
  s = add_line_rsketch(s, "cut", "e", "f");
  const Sketch after = trim_rsketch(s, "h", SketchPosition(8.0, 0.0));
  const SketchDiff diff = diff_sketch_rsketchdiff(s, after);
  CHECK(diff.created == std::vector<std::string>{"l1"});  // no new point: the crossing is within tolerance of 'near'
  CHECK(after.entities().at("l1").point_id("end") == "near");
  CHECK(span(after, "l1").second == doctest::Approx(4.0));
}

TEST_CASE("trim: against limits the cutters, construction entities cut only when named") {
  Sketch s = with_points({{"a", {0, 0}}, {"b", {10, 0}}, {"c", {3, -5}}, {"d", {3, 5}}, {"e", {7, -5}}, {"f", {7, 5}}});
  s = add_line_rsketch(s, "h", "a", "b");
  s = add_line_rsketch(s, "v1", "c", "d");
  s = add_line_rsketch(s, "v2", "e", "f", /*construction=*/true);
  const Sketch default_cut = trim_rsketch(s, "h", SketchPosition(8.0, 0.0));
  CHECK(span(default_cut, "l1").second == doctest::Approx(3.0));  // v2 is construction: v1 is the nearest cut
  const Sketch named = trim_rsketch(s, "h", SketchPosition(8.0, 0.0), std::vector<SketchTarget>{"v2"});
  CHECK(span(named, "l1").second == doctest::Approx(7.0));
  CHECK_THROWS_WITH_AS((void)trim_rsketch(s, "h", SketchPosition(8.0, 0.0), std::vector<SketchTarget>{"zz"}),
                       doctest::Contains("against names 'zz'"), Error);
}

TEST_CASE("trim: constraints on the end points stay, constraints naming the entity go, ids are never reused") {
  Sketch s = with_points({{"a", {0, 0}}, {"b", {10, 0}}, {"c", {5, -5}}, {"d", {5, 5}}, {"p1", {20, 20}}});
  s = add_line_rsketch(s, "h", "a", "b");
  s = add_line_rsketch(s, "v", "c", "d");
  s = constrain_fix_rsketch(s, "h.start", "fixed");
  s = constrain_length_rsketch(s, "h", 10.0, "len");
  s = constrain_horizontal_rsketch(s, "h");
  const Sketch after = trim_rsketch(s, "h", SketchPosition(2.0, 0.0));
  const SketchDiff diff = diff_sketch_rsketchdiff(s, after);
  CHECK(has(diff.removed_constraints, "len"));
  CHECK(has(diff.removed_constraints, "c_horizontal_0"));
  CHECK(diff.created == std::vector<std::string>{"p2", "l1"});  // p1 is taken
  CHECK(diff.created_constraints == std::vector<std::string>{"c_horizontal_1", "c_point_on_0"});
  const SketchConstraint* fixed = nullptr;
  for (const SketchConstraint& c : after.constraints())
    if (c.id == "fixed")
      fixed = &c;
  REQUIRE(fixed != nullptr);
  CHECK(fixed->targets[0].entity_id == "a");
  CHECK(fixed->targets[0].subentity == "geometry");
  CHECK(after.entities().contains("a"));
}

TEST_CASE("trim: works on the solved geometry") {
  Sketch s = with_points({{"a", {0, 0}}, {"b", {9, 3}}, {"c", {5, -5}}, {"d", {5, 5}}});
  s = add_line_rsketch(s, "h", "a", "b");
  s = add_line_rsketch(s, "v", "c", "d");
  s = constrain_fix_rsketch(s, "a");
  s = constrain_fix_rsketch(s, "c");
  s = constrain_fix_rsketch(s, "d");
  s = constrain_horizontal_rsketch(s, "h");
  s = constrain_length_rsketch(s, "h", 10.0);
  const Sketch after = trim_rsketch(s, "h", SketchPosition(8.0, 0.0));
  CHECK(near(xy_of(after, "p1"), 5.0, 0.0));  // the seed of b would have crossed v at y = 1.67
}

TEST_CASE("trim: bad arguments name the ids") {
  const Sketch s = plus();
  CHECK_THROWS_WITH_AS((void)trim_rsketch(s, "zz", SketchPosition(0, 0)), doctest::Contains("there is no entity 'zz'"),
                       Error);
  CHECK_THROWS_WITH_AS((void)trim_rsketch(s, "a", SketchPosition(0, 0)),
                       doctest::Contains("'a' is a point: only lines, circles and arcs can be trimmed"), Error);
  CHECK_THROWS_WITH_AS((void)trim_rsketch(s, "h", SketchPosition("h")), doctest::Contains("'h' is a line, not a point"),
                       Error);
  CHECK_THROWS_WITH_AS((void)trim_rsketch(s, "h", SketchPosition(std::nan(""), 0.0)), doctest::Contains("finite"),
                       Error);
  try {
    (void)trim_rsketch(s, "zz", SketchPosition(0, 0));
    FAIL("must raise");
  } catch (const Error& e) {
    CHECK(e.operation() == "trim_rsketch");
  }
}

TEST_CASE("extend: onto a line moves the end, ties it, drops the length") {
  Sketch s = with_points({{"a", {0, 0}}, {"b", {3, 0}}, {"c", {8, -4}}, {"d", {8, 4}}});
  s = add_line_rsketch(s, "h", "a", "b");
  s = add_line_rsketch(s, "wall", "c", "d");
  s = constrain_length_rsketch(s, "h", 3.0, "k1");
  const Sketch after = extend_rsketch(s, "h", "end");
  CHECK(near(xy_of(after, "b"), 8.0, 0.0));
  const SketchDiff diff = diff_sketch_rsketchdiff(s, after);
  CHECK(diff.removed_constraints == std::vector<std::string>{"k1"});
  CHECK(diff.changed == std::vector<std::string>{"b"});
  CHECK(diff.created_constraints == std::vector<std::string>{"c_point_on_0"});
  CHECK(after.constraints().back().targets[1].entity_id == "wall");
}

TEST_CASE("extend: onto a circle, from the start, to a named entity") {
  Sketch s = with_points({{"o", {10, 0}}, {"a", {0, 0}}, {"b", {3, 0}}, {"x1", {6, -4}}, {"x2", {6, 4}}});
  s = add_circle_rsketch(s, "c", "o", 2.0);
  s = add_line_rsketch(s, "h", "a", "b");
  const Sketch onto_circle = extend_rsketch(s, "h", "end", SketchTarget("c"));
  CHECK(near(xy_of(onto_circle, "b"), 8.0, 0.0));
  s = add_line_rsketch(s, "near", "x1", "x2");
  CHECK(near(xy_of(extend_rsketch(s, "h", "end"), "b"), 6.0, 0.0));                     // the nearest one
  CHECK(near(xy_of(extend_rsketch(s, "h", "end", SketchTarget("c")), "b"), 8.0, 0.0));  // the named one
  Sketch back = with_points({{"a", {3, 0}}, {"b", {6, 0}}, {"c", {-4, -4}}, {"d", {-4, 4}}});
  back = add_line_rsketch(back, "h", "a", "b");
  back = add_line_rsketch(back, "w", "c", "d");
  const Sketch moved = extend_rsketch(back, "h", "start");
  CHECK(near(xy_of(moved, "a"), -4.0, 0.0));
  CHECK(near(xy_of(moved, "b"), 6.0, 0.0));
}

TEST_CASE("extend: refusals name the ids") {
  CHECK_THROWS_WITH_AS((void)extend_rsketch(plus(), "h", "end"),
                       doctest::Contains("nothing is ahead of the end of 'h'"), Error);
  CHECK_THROWS_WITH_AS((void)extend_rsketch(plus(), "h", "middle"), doctest::Contains("end must be 'start' or 'end'"),
                       Error);
  CHECK_THROWS_WITH_AS((void)extend_rsketch(plus(), "h", "end", SketchTarget("nope")),
                       doctest::Contains("there is no entity 'nope' to extend to"), Error);
  Sketch s = with_points({{"a", {0, 0}}, {"b", {3, 0}}, {"c", {3, 4}}, {"w1", {8, -4}}, {"w2", {8, 4}}});
  s = add_line_rsketch(s, "h", "a", "b");
  s = add_line_rsketch(s, "up", "b", "c");
  s = add_line_rsketch(s, "wall", "w1", "w2");
  CHECK_THROWS_WITH_AS((void)extend_rsketch(s, "h", "end"), doctest::Contains("point 'b') is shared with 'up'"), Error);
}

TEST_CASE("diff: created, removed and changed") {
  const Sketch before = plus();
  const SketchDiff none = diff_sketch_rsketchdiff(before, before);
  CHECK(none.created.empty());
  CHECK(none.removed.empty());
  CHECK(none.changed.empty());
  CHECK(none.created_constraints.empty());
  const Sketch after = add_point_rsketch(before, "z", 1, 1);
  CHECK(diff_sketch_rsketchdiff(before, after).created == std::vector<std::string>{"z"});
  CHECK(diff_sketch_rsketchdiff(after, before).removed == std::vector<std::string>{"z"});
  CHECK(diff_sketch_rsketchdiff(before, after).to_value().find("created")->as_array().size() == 1);
}

// ---- B-splines ----------------------------------------------------------------------------------------------------

namespace {

// A cubic Bezier arch (0, 0) -> (6, 0) through b (2, 2) and c (4, 2); it peaks at (3, 1.5).
Sketch arch(std::vector<std::pair<std::string, SketchPoint2>> more = {}) {
  std::vector<std::pair<std::string, SketchPoint2>> points{{"a", {0, 0}}, {"b", {2, 2}}, {"c", {4, 2}}, {"d", {6, 0}}};
  points.insert(points.end(), more.begin(), more.end());
  return add_bspline_rsketch(with_points(points), "sp", "a", "d", {"a", "b", "c", "d"}, 3);
}

std::vector<std::string> poles_of(const Sketch& s, const std::string& spline) {
  std::vector<std::string> out;
  for (const SketchPole& pole : s.entities().at(spline).bspline().poles)
    out.push_back(pole.point_id);
  return out;
}

const SketchConstraint* constraint_of(const Sketch& s, const std::string& kind, const std::string& first) {
  for (const SketchConstraint& c : s.constraints())
    if (c.kind == kind && c.targets.at(0).entity_id == first)
      return &c;
  return nullptr;
}

SketchSolveResult loose_solve(const Sketch& s) {
  SketchSolveRequest request;
  request.strict = false;
  return inspect_sketch_rsketchresult(s, request);
}

std::string status_of(const Sketch& s) {
  return loose_solve(s).status;
}

}  // namespace

TEST_CASE("trim: a B-spline crossed by a line keeps the piece away from the click as a new B-spline") {
  Sketch s = arch({{"v1", {4, -5}}, {"v2", {4, 5}}});
  s = add_line_rsketch(s, "v", "v1", "v2");
  const Sketch after = trim_rsketch(s, "sp", SketchPosition(5.0, 1.0));
  const SketchDiff diff = diff_sketch_rsketchdiff(s, after);
  CHECK(diff.removed == std::vector<std::string>{"b", "c", "d", "sp"});  // the inner poles moved: new points
  CHECK(diff.created == std::vector<std::string>{"p1", "p2", "p3", "s1"});
  CHECK(ids_of(after, "bspline") == std::vector<std::string>{"s1"});
  CHECK(poles_of(after, "s1") == std::vector<std::string>{"a", "p2", "p3", "p1"});
  CHECK(xy_of(after, "p1").first == doctest::Approx(4.0));
  CHECK(xy_of(after, "p1").second == doctest::Approx(4.0 / 3.0));  // x = 6t, y = 6t(1 - t) on the arch
  const SketchConstraint* tie = constraint_of(after, "point_on", "p1");
  REQUIRE(tie != nullptr);
  CHECK(tie->targets[1].entity_id == "v");
  CHECK(status_of(after) == "underconstrained");
}

TEST_CASE("trim: a line crossed by a B-spline is cut there and its cut end is kept on the B-spline") {
  Sketch s = arch({{"h1", {-1, 1}}, {"h2", {7, 1}}});
  s = add_line_rsketch(s, "h", "h1", "h2");
  const Sketch after = trim_rsketch(s, "h", SketchPosition(6.5, 1.0));
  REQUIRE(ids_of(after, "line") == std::vector<std::string>{"l1"});
  CHECK(span(after, "l1").first == doctest::Approx(-1.0));
  const double x = span(after, "l1").second;
  CHECK(x > 4.0);
  CHECK(x < 6.0);
  const SketchConstraint* tie = constraint_of(after, "point_on", "p1");
  REQUIRE(tie != nullptr);
  CHECK(tie->targets[1].entity_id == "sp");
  CHECK(tie->targets[1].kind == "bspline");
  // the solver keeps the point on the B-spline: drag-free solve leaves it where it is
  const SketchSolveResult solved = loose_solve(after);
  CHECK(solved.status == "underconstrained");
  CHECK(near(solved.solved_points.at("p1"), x, 1.0));
}

TEST_CASE("trim: a tangent touch is one cut; a B-spline cut by a circle and by another B-spline") {
  Sketch s = arch({{"h1", {-1, 1.5}}, {"h2", {7, 1.5}}});
  s = add_line_rsketch(s, "h", "h1", "h2");
  const Sketch touched = trim_rsketch(s, "h", SketchPosition(5.0, 1.5));
  CHECK(span(touched, "l1").second == doctest::Approx(3.0));
  Sketch t = arch({{"o", {6, 0}}, {"e", {0, 3}}, {"f", {3, -2}}, {"g", {5, -2}}, {"h", {8, 3}}});
  t = add_circle_rsketch(t, "ring", "o", 2.0);
  t = add_bspline_rsketch(t, "low", "e", "h", {"e", "f", "g", "h"}, 3);
  const Sketch by_circle = trim_rsketch(t, "sp", SketchPosition(5.5, 0.5), std::vector<SketchTarget>{"ring"});
  REQUIRE(ids_of(by_circle, "bspline") == std::vector<std::string>{"s1", "low"});
  const SketchPoint2 cut = xy_of(by_circle, by_circle.entities().at("s1").point_id("end"));
  CHECK(std::hypot(cut.first - 6.0, cut.second) == doctest::Approx(2.0));
  const Sketch by_spline = trim_rsketch(t, "sp", SketchPosition(3.0, 1.5), std::vector<SketchTarget>{"low"});
  CHECK(ids_of(by_spline, "bspline") == std::vector<std::string>{"s1", "s2", "low"});
  CHECK(by_spline.entities().at("s1").point_id("start") == "a");
  CHECK(by_spline.entities().at("s2").point_id("end") == "d");
  CHECK(status_of(by_spline) == "underconstrained");
}

TEST_CASE("trim: a closed B-spline needs two cuts; the piece over its seam keeps the seam point") {
  Sketch s = with_points({{"q0", {0, 0}},
                          {"q1", {10, 0}},
                          {"q2", {10, 10}},
                          {"q3", {0, 10}},
                          {"v1", {5, -5}},
                          {"v2", {5, 15}},
                          {"w1", {20, -5}},
                          {"w2", {20, 5}}});
  s = add_bspline_rsketch(s, "loop", "q0", "q0", {"q0", "q1", "q2", "q3", "q0"}, 3);
  const Sketch once = add_line_rsketch(s, "w", "w1", "w2");
  CHECK(ids_of(trim_rsketch(once, "loop", SketchPosition(5.0, 5.0)), "bspline").empty());  // nothing crosses it
  Sketch half = add_line_rsketch(s, "v", "v1", "v2");
  const Sketch right = trim_rsketch(half, "loop", SketchPosition(9.0, 9.0));
  REQUIRE(ids_of(right, "bspline") == std::vector<std::string>{"s1"});
  const std::vector<std::string> poles = poles_of(right, "s1");
  CHECK(std::find(poles.begin(), poles.end(), "q0") != poles.end());  // the seam is an inner control point now
  CHECK(!right.entities().contains("q1"));
  CHECK(status_of(right) == "underconstrained");
  // one crossing only: a line that ends inside the loop
  Sketch stub = with_points(
      {{"q0", {0, 0}}, {"q1", {10, 0}}, {"q2", {10, 10}}, {"q3", {0, 10}}, {"v1", {5, -5}}, {"v2", {5, 5}}});
  stub = add_bspline_rsketch(stub, "loop", "q0", "q0", {"q0", "q1", "q2", "q3", "q0"}, 3);
  stub = add_line_rsketch(stub, "v", "v1", "v2");
  CHECK_THROWS_WITH_AS((void)trim_rsketch(stub, "loop", SketchPosition(9.0, 9.0)),
                       doctest::Contains("a closed B-spline needs two cuts"), Error);
}

TEST_CASE("trim: constraints on a B-spline's ends stay with the piece that keeps the end") {
  Sketch s = arch({{"z", {-4, -4}}, {"v1", {4, -5}}, {"v2", {4, 5}}});
  s = add_line_rsketch(s, "lead", "z", "a");
  s = add_line_rsketch(s, "v", "v1", "v2");
  s = constrain_tangent_rsketch(s, "lead", "sp", std::string("end"), std::string("start"), "external", "tan");
  s = constrain_fix_rsketch(s, "c", "fixc");
  s = constrain_fix_rsketch(s, "sp.start", "fixa");
  const Sketch after = trim_rsketch(s, "sp", SketchPosition(5.0, 1.0));
  const SketchDiff diff = diff_sketch_rsketchdiff(s, after);
  CHECK(diff.changed_constraints == std::vector<std::string>{"tan", "fixa"});
  CHECK(diff.removed_constraints == std::vector<std::string>{"fixc"});  // c is gone
  const SketchConstraint* tangent = constraint_of(after, "tangent", "lead");
  REQUIRE(tangent != nullptr);
  CHECK(tangent->targets[1].entity_id == "s1");
  CHECK(constraint_of(after, "fix", "a") != nullptr);
  CHECK(status_of(after) != "conflicting");
}

TEST_CASE("extend: a B-spline end grows to the line ahead, a line grows to a B-spline") {
  Sketch s = arch({{"w1", {9, -10}}, {"w2", {9, 10}}});
  s = add_line_rsketch(s, "w", "w1", "w2");
  const Sketch after = extend_rsketch(s, "sp", "end");
  CHECK(xy_of(after, "d").first == doctest::Approx(9.0));
  const std::vector<std::string> poles = poles_of(after, "sp");
  CHECK(poles.front() == "a");
  CHECK(poles.back() == "d");
  CHECK(poles[1] == "b");  // the poles the extension leaves alone keep their points
  const SketchConstraint* tie = constraint_of(after, "point_on", "d");
  REQUIRE(tie != nullptr);
  CHECK(tie->targets[1].entity_id == "w");
  CHECK(status_of(after) == "underconstrained");
  // the first part of the curve is unchanged: (3, 1.5) is still on it
  const SketchSolveResult solved = loose_solve(after);
  const Value& entity = solved.solved_entities.at("sp");
  CHECK(entity.find("control_points")->as_array().size() == poles.size());
  CHECK_THROWS_WITH_AS((void)extend_rsketch(s, "sp", "start"),
                       doctest::Contains("nothing is ahead of the start of 'sp'"), Error);

  Sketch t = arch({{"l1", {3, -3}}, {"l2", {3, -1}}});
  t = add_line_rsketch(t, "l", "l1", "l2");
  const Sketch reached = extend_rsketch(t, "l", "end", SketchTarget("sp"));
  CHECK(near(xy_of(reached, "l2"), 3.0, 1.5));
  CHECK(constraint_of(reached, "point_on", "l2")->targets[1].entity_id == "sp");
}

TEST_CASE("crossings: B-splines and ellipses are listed") {
  Sketch s = arch({{"h1", {-1, 1}}, {"h2", {7, 1}}, {"o", {3, 0}}, {"m", {7, 0}}, {"n", {3, -1}}});
  s = add_line_rsketch(s, "h", "h1", "h2");
  s = add_ellipse_rsketch(s, "el", "o", "m", "n");
  const Value crossings = inspect_sketch_rsketchcrossings(s);
  int spline_line = 0;
  int ellipse = 0;
  int touch = 0;
  for (const Value& item : crossings.as_array()) {
    const auto& ids = item.find("entities")->as_array();
    spline_line += ids.at(0).as_string() == "sp" && ids.at(1).as_string() == "h";
    ellipse += ids.at(0).as_string() == "sp" && ids.at(1).as_string() == "el";
    touch += ids.at(0).as_string() == "h" && ids.at(1).as_string() == "el";
  }
  CHECK(spline_line == 2);
  CHECK(ellipse == 2);  // the arch leaves the ellipse and comes back in
  CHECK(touch == 1);    // the line touches its top
}
