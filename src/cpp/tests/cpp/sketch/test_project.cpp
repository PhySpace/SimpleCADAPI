// project_rsketch: reference geometry from another sketch or from shapes, through the plane frames.
#include "doctest.h"

#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>

#include <cmath>
#include <functional>
#include <string>
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

// A front view on XZ: a bottom line, a vertical line and a circle.
Sketch front() {
  Sketch s = make_sketch_rsketch("front", Value("XZ"), "front");
  s = add_point_rsketch(s, "a", 0, 0);
  s = add_point_rsketch(s, "b", 10, 0);
  s = add_point_rsketch(s, "c", 10, 6);
  s = add_point_rsketch(s, "o", 5, 3);
  s = add_line_rsketch(s, "l", "a", "b");
  s = add_line_rsketch(s, "m", "b", "c");
  s = add_circle_rsketch(s, "k", "o", 2.0);
  return s;
}

Shape box(double x, double y, double z) {
  return Shape::from_occt(BRepPrimAPI_MakeBox(x, y, z).Shape());
}

Shape cylinder(double radius, double height) {
  return Shape::from_occt(BRepPrimAPI_MakeCylinder(radius, height).Shape());
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

TEST_CASE("project: a front view lands on the plan as lines and points, fixed and construction") {
  const Sketch plan = make_sketch_rsketch("plan", Value("XY"), "plan");
  const Sketch out = project_rsketch(plan, front());
  // l is a line along x, m runs along the plan normal and is a point, the circle k is seen edge on and is a line
  const SketchEntity& line = out.entities().at("proj_front_3");
  CHECK(line.kind == "line");
  CHECK(line.construction);
  CHECK(near(xy_of(out, line.point_id("start")), 0.0, 0.0));
  CHECK(near(xy_of(out, line.point_id("end")), 10.0, 0.0));
  const SketchEntity& circle_line = out.entities().at("proj_front_6");
  CHECK(circle_line.kind == "line");  // the circle seen edge on, from x = 3 to x = 7
  CHECK(near(xy_of(out, circle_line.point_id("start")), 7.0, 0.0));
  CHECK(near(xy_of(out, circle_line.point_id("end")), 3.0, 0.0));
  std::vector<std::string> fixed;
  for (const SketchConstraint& constraint : out.constraints())
    if (constraint.kind == "fix")
      fixed.push_back(constraint.targets[0].entity_id);
  CHECK(fixed == std::vector<std::string>{"proj_front_3", "proj_front_6"});
  const Value* projections = out.metadata().find("projections");
  REQUIRE(projections != nullptr);
  CHECK(projections->as_array().size() == 3);
  CHECK(projections->as_array()[0].find("source")->as_string() == "front");
  CHECK(projections->as_array()[0].find("entity")->as_string() == "l");
  CHECK(projections->as_array()[0].find("projected")->as_string() == "proj_front_3");
  Sketch solved = out;
  CHECK(solved.solve(SketchSolveRequest{}).dof == 0);
}

TEST_CASE("project: parallel planes copy circles and arcs, a flipped plane reverses the arc") {
  Sketch up = make_sketch_rsketch("up", Value("XY"), "up");
  up = add_point_rsketch(up, "o", 1, 2);
  up = add_point_rsketch(up, "s", 3, 2);
  up = add_point_rsketch(up, "e", 1, 4);
  up = add_arc_rsketch(up, "arc", "s", "e", "o");  // counter-clockwise from (3,2) to (1,4) about (1,2)
  up = add_circle_rsketch(up, "k", "o", 0.5);
  Value flipped_plane = Value::object();  // normal = -z
  flipped_plane.set("origin", Value(Value::Array{Value(0.0), Value(0.0), Value(5.0)}));
  flipped_plane.set("x_axis", Value(Value::Array{Value(1.0), Value(0.0), Value(0.0)}));
  flipped_plane.set("y_axis", Value(Value::Array{Value(0.0), Value(-1.0), Value(0.0)}));
  Sketch down = make_sketch_rsketch("down", flipped_plane, "down");
  down = add_point_rsketch(down, "o", 1, -2);
  down = add_point_rsketch(down, "s", 3, -2);
  down = add_point_rsketch(down, "e", 1, -4);
  down = add_arc_rsketch(down, "arc", "s", "e", "o");

  const Sketch target = make_sketch_rsketch("target", Value("XY"), "target");
  const Sketch same = project_rsketch(target, up, std::vector<std::string>{"arc", "k"});
  const SketchEntity& arc = same.entities().at("proj_up_4");
  CHECK(arc.kind == "arc");
  CHECK(near(xy_of(same, arc.point_id("start")), 3.0, 2.0));
  CHECK(near(xy_of(same, arc.point_id("end")), 1.0, 4.0));
  CHECK(same.entities().at("proj_up_5").kind == "circle");
  CHECK(same.entities().at("proj_up_5").number("radius") == doctest::Approx(0.5));

  const Sketch reversed = project_rsketch(target, down, std::vector<std::string>{"arc"});
  // the flipped sketch's counter-clockwise is clockwise seen from +z, so the arc keeps its shape by swapping its ends
  const SketchEntity& copy = reversed.entities().at("proj_down_4");
  CHECK(near(xy_of(reversed, copy.point_id("start")), 1.0, 4.0));
  CHECK(near(xy_of(reversed, copy.point_id("end")), 3.0, 2.0));
}

TEST_CASE("project: an oblique circle is an ellipse, an oblique arc is refused") {
  const double c = std::cos(kPi / 3.0);
  const double s = std::sin(kPi / 3.0);
  Value tilted = Value::object();  // the plane tilted 60 degrees about the x axis
  tilted.set("origin", Value(Value::Array{Value(0.0), Value(0.0), Value(0.0)}));
  tilted.set("x_axis", Value(Value::Array{Value(1.0), Value(0.0), Value(0.0)}));
  tilted.set("y_axis", Value(Value::Array{Value(0.0), Value(c), Value(s)}));
  Sketch source = make_sketch_rsketch("tilt", tilted, "tilt");
  source = add_point_rsketch(source, "o", 0, 0);
  source = add_point_rsketch(source, "p", 2, 0);
  source = add_point_rsketch(source, "q", 0, 2);
  source = add_circle_rsketch(source, "k", "o", 2.0);
  source = add_arc_rsketch(source, "arc", "p", "q", "o");
  const Sketch target = make_sketch_rsketch("target", Value("XY"), "target");
  const Sketch out = project_rsketch(target, source, std::vector<std::string>{"k"});
  const SketchEntity& ellipse = out.entities().at("proj_tilt_4");
  CHECK(ellipse.kind == "ellipse");
  CHECK(near(xy_of(out, ellipse.point_id("major")), 2.0, 0.0));      // the major semi-axis is the radius
  CHECK(near(xy_of(out, ellipse.point_id("minor")), 0.0, 2.0 * c));  // the minor one is r * cos(60 deg)
  const std::string text = failure_text([&] { project_rsketch(target, source, std::vector<std::string>{"arc"}); });
  CHECK(text.find("'arc' is an arc in a plane oblique") != std::string::npos);
}

TEST_CASE("project: a shape projects its lines and circles; a Vertex is a point; other curves are refused by name") {
  const Sketch target = make_sketch_rsketch("target", Value("XY"), "target");
  const Sketch boxed = project_rsketch(target, std::vector<Shape>{box(4.0, 3.0, 2.0)});
  int lines = 0;
  for (const auto& [id, entity] : boxed.entities())
    if (entity.kind == "line")
      ++lines;
  CHECK(lines == 4);  // top and bottom coincide, the four vertical edges are points
  CHECK(boxed.entities().contains("proj_shape_1"));
  const Sketch round = project_rsketch(target, std::vector<Shape>{cylinder(2.0, 5.0)});
  bool circle = false;
  for (const auto& [id, entity] : round.entities())
    circle = circle || (entity.kind == "circle" && entity.number("radius") == doctest::Approx(2.0));
  CHECK(circle);
  CHECK_THROWS_AS(project_rsketch(target, std::vector<Shape>{}), Error);
}

TEST_CASE("project: ids never collide, a repeat reuses what is there, errors name the entity") {
  const Sketch target = make_sketch_rsketch("target", Value("XY"), "target");
  Sketch crowded = add_point_rsketch(target, "proj_front_1", 99, 99);
  const Sketch out = project_rsketch(crowded, front(), std::vector<std::string>{"l"});
  CHECK(out.entities().contains("proj_front_2"));
  CHECK(out.entities().at("proj_front_1").number("x") == 99.0);  // not touched

  const Sketch once = project_rsketch(target, front());
  const Sketch twice = project_rsketch(once, front());
  CHECK(twice.entities().size() == once.entities().size());
  CHECK(twice.constraints().size() == once.constraints().size());
  CHECK(twice.metadata().find("projections")->as_array().size() == 3);

  CHECK(failure_text([&] { project_rsketch(target, front(), std::vector<std::string>{"zz"}); }).find("'zz'") !=
        std::string::npos);
  CHECK(failure_text([&] { project_rsketch(target, front(), std::vector<std::string>{}); }).find("entities is empty") !=
        std::string::npos);
  CHECK(failure_text([&] { project_rsketch(front(), front()); }).find("cannot be projected onto itself") !=
        std::string::npos);
  CHECK(failure_text([&] { project_rsketch_refuse("a reason"); }) == "a reason");
}
