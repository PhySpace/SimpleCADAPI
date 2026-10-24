// What the operators record, the session paths of the profile makers, and rerunning from a parameter edit.
#include "support.hpp"

#include "scad/ops/geometry/executors.hpp"
#include "scad/reactive/expr.hpp"
#include "scad/reactive/registry.hpp"

using namespace scad;
using namespace scad::geometry_test;
using reactive::Sym;

namespace {

struct Model {
  reactive::ExecutorRegistry registry{false};
  std::unique_ptr<reactive::Session> session;
  Model() {
    register_geometry_executors(registry);
    reactive::Session::Options options;
    options.registry = &registry;
    session = std::make_unique<reactive::Session>(options);
    session->start();
  }
  ~Model() { session->stop(); }
};

}  // namespace

TEST_CASE("a recorded circle wire is an edge and a wire, a rectangle four lines and a wire") {
  Recording recording;
  const Wire circle = make_circle_rwire(scalar3(0, 0, 0), 2.0);
  CHECK(recording.ops() == std::vector<std::string>{"make_circle_redge", "make_wire_from_edges_rwire"});
  CHECK(circle.get_metadata("track").find("op")->as_string() == "make_wire_from_edges_rwire");

  Recording rectangle;
  make_rectangle_rface(2.0, 1.0);
  CHECK(rectangle.ops() == std::vector<std::string>{"make_line_redge", "make_line_redge", "make_line_redge", "make_line_redge",
                                                    "make_wire_from_edges_rwire", "make_face_from_wire_rface"});
}

TEST_CASE("without a recorder the same makers build one primitive and record nothing") {
  CHECK(make_circle_rwire(scalar3(0, 0, 0), 2.0).get_metadata("track").find("op")->as_string() == "make_circle_wire");
  CHECK(make_rectangle_rface(2.0, 1.0).get_metadata("track").find("op")->as_string() == "make_rectangle_face");
  CHECK(make_polyline_rwire({scalar3(0, 0, 0), scalar3(1, 0, 0)}).get_metadata("track").find("op")->as_string() == "make_polyline_wire");
  CHECK(make_helix_rwire(1.0, 2.0, 0.5).get_metadata("track").find("op")->as_string() == "make_helix_wire");
}

TEST_CASE("the rectangle's corners are expressions of its width") {
  Recording recording;
  const Sym w = reactive::make_var("w", 10.0);
  make_rectangle_rwire(w.scalar(), 4.0, scalar3(1, 0, 0));
  const auto& nodes = recording.session.graph().nodes();
  REQUIRE(nodes.size() == 5);
  CHECK(nodes[0]->params.find("start")->dump() == "[-4,-2,0]");
  CHECK(nodes[0]->params.find("end")->dump() == "[6,-2,0]");
  // Every coordinate of the first side is an expression (`dx * 0.0` is one too, as in Python).
  CHECK(nodes[0]->symbolic.size() == 6);
  CHECK(nodes[0]->symbolic.front().first == "start[0]");
  CHECK(nodes[4]->symbolic.empty());
}

TEST_CASE("operators record the arguments they were given") {
  Recording recording;
  make_spline_rwire({.control_points = {{0.0, 0.0, 0.0}, {1.0, 1.0, 0.0}, {2.0, 1.0, 0.0}, {3.0, 0.0, 0.0}}});
  make_helix_rwire(2.0, 6.0, 3.0, scalar3(0, 0, 0), scalar3(0, 0, 1), "Left");
  const auto& nodes = recording.session.graph().nodes();
  REQUIRE(nodes.size() == 4);
  CHECK(nodes[0]->op == "make_spline_redge");
  CHECK(nodes[0]->params.find("knots")->dump() == "[0,1]");
  CHECK(nodes[0]->params.find("multiplicities")->dump() == "[4,4]");
  CHECK(nodes[0]->params.find("weights")->is_null());
  CHECK(nodes[2]->op == "make_helix_redge");
  CHECK(nodes[2]->params.find("handedness")->as_string() == "Left");
}

TEST_CASE("a parameter edit reruns the recorded operators") {
  Model model;
  const Sym w = reactive::make_var("w", 10.0);
  const Sym h = reactive::make_var("h", 4.0);
  const Solid box = make_box_rsolid(w.scalar(), 2.0, h.scalar());
  const Face rect = make_rectangle_rface(w.scalar(), h.scalar());
  const Solid ball = make_sphere_rsolid(w.scalar(), scalar3(w.scalar().value(), 0, 0));
  const Wire spring = make_helix_rwire(h.scalar(), (w * 2).scalar(), 3.0);
  CHECK(box.volume() == doctest::Approx(80.0));

  model.session->set_var("w", 20.0);
  const reactive::RecomputeReport report = model.session->recompute();
  CHECK(report.ok());
  CHECK(Solid(model.session->current(box)).volume() == doctest::Approx(160.0));
  CHECK(Face(model.session->current(rect)).area() == doctest::Approx(80.0));
  CHECK(Solid(model.session->current(ball)).volume() == doctest::Approx(4.0 / 3 * kPi * 8000).epsilon(1e-6));
  check_box(model.session->current(spring), {-3, -3, 0}, {3, 3, 40}, 1e-5);

  model.session->set_var("h", -1.0);
  const reactive::RecomputeReport broken = model.session->recompute();
  CHECK_FALSE(broken.ok());
  REQUIRE_FALSE(broken.failed.empty());
  CHECK(broken.failed.front().op == "make_box_rsolid");
}

TEST_CASE("every recorded operation has an executor") {
  reactive::ExecutorRegistry registry(false);
  register_geometry_executors(registry);
  for (const char* op : {"make_point_rvertex", "make_line_redge", "make_circle_redge", "make_ellipse_redge",
                         "make_three_point_arc_redge", "make_angle_arc_redge", "make_helix_redge", "make_spline_redge",
                         "make_interpolated_spline_redge", "make_wire_from_edges_rwire", "make_face_from_wire_rface",
                         "make_face_from_wires_rface", "make_box_rsolid", "make_cylinder_rsolid", "make_cone_rsolid",
                         "make_sphere_rsolid", "load_brep_region_rsolid", "load_brep_region_rshell"}) {
    CHECK_MESSAGE(registry.contains(op), op);
  }
  CHECK_THROWS_AS(register_geometry_executors(registry), ValueError);
}
