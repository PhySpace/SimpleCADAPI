// The sketch document, its functional operators, promotion to wires and faces, and
// the backend registry.  Ports the non-solver parts of test_sketch_api.py,
// test_sketch_closed_bspline.py and test_sketch_ellipse.py.
#include "doctest.h"

#include <cmath>
#include <string>

#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>

#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/sketch/operators.hpp"
#include "scad/sketch/native_solver.hpp"
#include "scad/topo/recorder.hpp"

using namespace scad;

namespace {

Sketch rectangle(const char* name = "rect") {
  Sketch s = make_sketch_rsketch(name);
  for (const auto& [id, x, y] : {std::tuple{"p0", 0.0, 0.0}, {"p1", 2.0, 0.0}, {"p2", 2.0, 1.0}, {"p3", 0.0, 1.0}}) {
    s = add_point_rsketch(s, id, x, y);
  }
  s = add_line_rsketch(s, "bottom", "p0", "p1");
  s = add_line_rsketch(s, "right", "p1", "p2");
  s = add_line_rsketch(s, "top", "p2", "p3");
  s = add_line_rsketch(s, "left", "p3", "p0");
  s = constrain_horizontal_rsketch(s, "bottom");
  s = constrain_vertical_rsketch(s, "right");
  s = constrain_parallel_rsketch(s, "bottom", "top");
  s = constrain_parallel_rsketch(s, "left", "right");
  s = constrain_distance_rsketch(s, "p0", "p1", 2.0);
  s = constrain_distance_rsketch(s, "p0", "p3", 1.0);
  s = constrain_fix_rsketch(s, "p0");
  return s;
}

bool has_tag(const Shape& shape, const std::string& tag) { return shape.has_tag(tag, TagScope::Local); }

double mass(const Face& face) {
  GProp_GProps props;
  BRepGProp::SurfaceProperties(face.wrapped(), props, 1e-10);
  return props.Mass();
}

class CapturingRecorder : public Recorder {
 public:
  void record(const OpRecord& record, const std::vector<Shape>& outputs) override {
    ops.push_back(record.op);
    output_counts.push_back(outputs.size());
  }
  std::vector<std::string> ops;
  std::vector<std::size_t> output_counts;
};

}  // namespace

TEST_CASE("sketch updates are functional") {
  const Sketch original = make_sketch_rsketch("functional");
  const Sketch with_point = add_point_rsketch(original, "p0", 0.0, 0.0);
  CHECK_FALSE(original.entities().contains("p0"));
  CHECK(with_point.entities().contains("p0"));
}

TEST_CASE("refs are scoped to their sketch and resolve sub-points") {
  Sketch first = add_point_rsketch(make_sketch_rsketch("first"), "p0", 0.0, 0.0);
  Sketch second = add_point_rsketch(make_sketch_rsketch("second"), "p1", 1.0, 0.0);
  const SketchRef foreign = get_sketch_point_rsketchref(second, "p1");
  CHECK_THROWS_AS((void)add_line_rsketch(first, "bad", get_sketch_point_rsketchref(first, "p0"), foreign), Error);

  Sketch s = add_point_rsketch(add_point_rsketch(make_sketch_rsketch("refs"), "a", 0, 0), "b", 1, 0);
  s = add_line_rsketch(s, "line", "a", "b");
  const SketchRef end = get_sketch_point_rsketchref(s, "line.end");
  CHECK(end.entity_id == "line");
  CHECK(end.subentity == "end");
  CHECK(s.resolve_point_id(end) == "b");
  CHECK_THROWS_AS((void)get_sketch_point_rsketchref(s, "line.center"), ValueError);
  CHECK_THROWS_AS((void)get_sketch_entity_rsketchref(s, "missing"), ValueError);
}

TEST_CASE("duplicate ids and degenerate geometry are reported with the operation name") {
  Sketch s = add_point_rsketch(make_sketch_rsketch("dup"), "p0", 0, 0);
  try {
    (void)add_point_rsketch(s, "p0", 1, 1);
    FAIL("duplicate point id must raise");
  } catch (const Error& e) {
    CHECK(e.operation() == "add_point_rsketch");
    CHECK(std::string(e.what()).find("Duplicate sketch entity id 'p0'") != std::string::npos);
  }
  CHECK_THROWS_AS((void)add_line_rsketch(s, "l", "p0", "p0"), Error);
  CHECK_THROWS_AS((void)add_circle_rsketch(s, "c", "p0", -1.0), Error);
  Value parallel = Value::object();
  parallel.set("origin", Value(Value::Array{0.0, 0.0, 0.0}));
  parallel.set("x_axis", Value(Value::Array{1.0, 0.0, 0.0}));
  parallel.set("y_axis", Value(Value::Array{2.0, 0.0, 0.0}));
  CHECK_THROWS_AS((void)make_sketch_rsketch("bad", parallel), Error);
}

TEST_CASE("sketches round-trip through their serialized form") {
  Sketch s = rectangle();
  s = constrain_angle_rsketch(s, "bottom", "right", 90.0, "right_angle");
  const Value dumped = s.to_value();
  const Sketch restored = Sketch::from_value(dumped);
  CHECK(restored.to_value() == dumped);
  CHECK(restored.constraints().back().kind == "angle");
  CHECK(restored.entities().at("bottom").kind == "line");
}

TEST_CASE("a constrained rectangle promotes to a face with topology identity tags") {
  const Sketch s = rectangle();
  const Face face = make_face_from_sketch_rface(s, 0, {}, {.require_fully_constrained = true});
  CHECK(face.area() == doctest::Approx(2.0));
  CHECK(has_tag(face, "sketch.rect"));
  CHECK(has_tag(face, "sketch_profile.bottom"));
  CHECK(face.get_metadata("sketch_solve").find("status")->as_string() == "solved");
  CHECK(face.get_metadata("source_sketch").find("name")->as_string() == "rect");

  int seen = 0;
  for (const Edge& edge : face.edges()) {
    bool named = false;
    for (const char* entity : {"bottom", "right", "top", "left"}) {
      if (has_tag(edge, std::string("sketch_entity.") + entity) && has_tag(edge, std::string("sketch.rect.entity.") + entity)) {
        named = true;
        const auto explained = edge.explain_tag(std::string("sketch.rect.entity.") + entity, TagScope::Local);
        REQUIRE_FALSE(explained.empty());
        ++seen;
      }
    }
    CHECK(named);
  }
  CHECK(seen == 4);
  bool profile_named = false;
  for (const Wire& wire : face.wires()) profile_named = profile_named || has_tag(wire, "sketch.rect.profile.bottom");
  CHECK(profile_named);
  CHECK(has_tag(face, "sketch.rect.profile.bottom"));
  const Value promotion = face.get_metadata("sketch_promotion");
  CHECK(promotion.find("topology_name")->find("kind")->as_string() == "face");
}

TEST_CASE("wire promotion tags the wire and its edges") {
  const Wire wire = make_wire_from_sketch_rwire(rectangle(), 0, {.require_fully_constrained = true});
  CHECK(wire.is_closed());
  CHECK(wire.edges().size() == 4);
  CHECK(has_tag(wire, "sketch.rect.profile.bottom"));
  for (const Edge& edge : wire.edges()) CHECK(edge.explain_tag("sketch.rect.entity.bottom", TagScope::Local).size() <= 1);
}

TEST_CASE("a circle sketch promotes to a circular face") {
  Sketch s = add_point_rsketch(make_sketch_rsketch("circle"), "center", 0.0, 0.0);
  s = add_circle_rsketch(s, "outer", "center", 1.5);
  s = constrain_fix_rsketch(s, "center");
  s = constrain_radius_rsketch(s, "outer", 1.5);
  const Face face = make_face_from_sketch_rface(s, 0, {}, {.require_fully_constrained = true});
  CHECK(face.area() == doctest::Approx(kPi * 2.25).epsilon(1e-6));
  CHECK(has_tag(face.edges().at(0), "sketch_entity.outer"));
}

TEST_CASE("explicit hole profiles promote to a face with inner wires") {
  Sketch s = make_sketch_rsketch("plate");
  s = add_point_rsketch(s, "outer_center", 0.0, 0.0);
  s = add_circle_rsketch(s, "outer", "outer_center", 5.0);
  s = add_point_rsketch(s, "left_center", -2.0, 0.0);
  s = add_circle_rsketch(s, "left_hole", "left_center", 1.0);
  s = add_point_rsketch(s, "right_center", 2.0, 0.0);
  s = add_circle_rsketch(s, "right_hole", "right_center", 1.0);
  const Face face = make_face_from_sketch_rface(s, "outer", {"left_hole", "right_hole"});
  CHECK(face.inner_wires().size() == 2);
  CHECK(face.area() == doctest::Approx(23.0 * kPi).epsilon(1e-6));
  const Value loops = *face.get_metadata("sketch_promotion").find("loops");
  REQUIRE(loops.size() == 3);
  CHECK(loops.as_array()[0].find("role")->as_string() == "outer");
  CHECK(loops.as_array()[1].find("role")->as_string() == "inner");

  Sketch invalid = add_point_rsketch(make_sketch_rsketch("invalid_hole"), "oc", 0.0, 0.0);
  invalid = add_circle_rsketch(invalid, "outer", "oc", 2.0);
  invalid = add_point_rsketch(invalid, "hc", 5.0, 0.0);
  invalid = add_circle_rsketch(invalid, "hole", "hc", 1.0);
  CHECK_THROWS_AS((void)make_face_from_sketch_rface(invalid, "outer", {"hole"}), Error);
}

TEST_CASE("a reversed outer loop on the YZ plane still faces the plane normal") {
  Sketch s = make_sketch_rsketch("reversed_profile", Value("YZ"));
  for (const auto& [id, x, y] : {std::tuple{"p0", 0.0, 0.0}, {"p1", 0.0, 4.0}, {"p2", 4.0, 4.0}, {"p3", 4.0, 0.0}, {"hole_center", 2.0, 2.0}}) {
    s = add_point_rsketch(s, id, x, y);
  }
  s = add_line_rsketch(s, "left", "p0", "p1");
  s = add_line_rsketch(s, "top", "p1", "p2");
  s = add_line_rsketch(s, "right", "p2", "p3");
  s = add_line_rsketch(s, "bottom", "p3", "p0");
  s = add_circle_rsketch(s, "hole", "hole_center", 1.0);
  const Face face = make_face_from_sketch_rface(s, "left", {"hole"});
  CHECK(face.area() == doctest::Approx(16.0 - kPi).epsilon(1e-6));
  CHECK(face.normal_at().x == doctest::Approx(1.0));
}

TEST_CASE("the sketch plane follows the active workplane") {
  const Workplane plane({3, 4, 5}, {0, 1, 0}, {1, 0, 0});
  CoordinateSystemScope scope(plane.cs());
  Sketch s = add_point_rsketch(make_sketch_rsketch("workplane_ring"), "oc", 0.0, 0.0);
  s = add_circle_rsketch(s, "outer", "oc", 2.0);
  s = add_point_rsketch(s, "ic", 0.0, 0.0);
  s = add_circle_rsketch(s, "inner", "ic", 1.0);
  const Face face = make_face_from_sketch_rface(s, "outer", {"inner"});
  CHECK(face.normal_at().y == doctest::Approx(1.0));
  CHECK(face.center().x == doctest::Approx(3.0));
  CHECK(face.center().y == doctest::Approx(4.0));
  CHECK(face.center().z == doctest::Approx(5.0));
}

TEST_CASE("open chains promote to wires but not to faces; branches are named") {
  Sketch s = make_sketch_rsketch("chain");
  for (const auto& [id, x, y] : {std::tuple{"p0", 0.0, 0.0}, {"p1", 10.0, 0.0}, {"p2", 10.0, 8.0}}) s = add_point_rsketch(s, id, x, y);
  s = add_line_rsketch(s, "run", "p0", "p1");
  s = add_line_rsketch(s, "rise", "p1", "p2");
  s = constrain_fix_rsketch(s, "p0");
  s = constrain_horizontal_rsketch(s, "run");
  s = constrain_vertical_rsketch(s, "rise");
  s = constrain_length_rsketch(s, "run", 10.0);
  s = constrain_length_rsketch(s, "rise", 8.0);
  const Wire wire = make_wire_from_sketch_rwire(s, 0, {.require_fully_constrained = true});
  CHECK_FALSE(wire.is_closed());
  CHECK(wire.edges().size() == 2);
  try {
    (void)make_face_from_sketch_rface(s);
    FAIL("an open chain cannot become a face");
  } catch (const Error& e) {
    CHECK(std::string(e.what()).find("open chain") != std::string::npos);
  }

  Sketch branchy = make_sketch_rsketch("branchy");
  for (const auto& [id, x, y] : {std::tuple{"c", 0.0, 0.0}, {"a", 5.0, 0.0}, {"b", 0.0, 5.0}, {"d", -5.0, 0.0}}) {
    branchy = add_point_rsketch(branchy, id, x, y);
  }
  branchy = add_line_rsketch(branchy, "e1", "c", "a");
  branchy = add_line_rsketch(branchy, "e2", "c", "b");
  branchy = add_line_rsketch(branchy, "e3", "c", "d");
  try {
    (void)make_wire_from_sketch_rwire(branchy);
    FAIL("a branch point has no wire");
  } catch (const Error& e) {
    const std::string text = e.what();
    CHECK(text.find("branch") != std::string::npos);
    CHECK(text.find("'c'") != std::string::npos);
  }
}

TEST_CASE("a mixed sketch promotes a chain by id and the loop by default") {
  Sketch s = make_sketch_rsketch("mixed");
  for (const auto& [id, x, y] : {std::tuple{"a", 0.0, 0.0}, {"b", 4.0, 0.0}, {"c", 4.0, 3.0}, {"d", 0.0, 3.0}, {"e", 8.0, 1.0}, {"f", 12.0, 1.0}}) {
    s = add_point_rsketch(s, id, x, y);
  }
  s = add_line_rsketch(s, "rb", "a", "b");
  s = add_line_rsketch(s, "rr", "b", "c");
  s = add_line_rsketch(s, "rt", "c", "d");
  s = add_line_rsketch(s, "rl", "d", "a");
  s = add_line_rsketch(s, "tail", "e", "f");
  const Wire chain = make_wire_from_sketch_rwire(s, "tail");
  CHECK_FALSE(chain.is_closed());
  CHECK(chain.edges().size() == 1);
  CHECK(make_face_from_sketch_rface(s).area() == doctest::Approx(12.0));
}

TEST_CASE("arc and B-spline profiles build faces on an arbitrary plane") {
  Value plane = Value::object();
  plane.set("origin", Value(Value::Array{10.0, 20.0, 30.0}));
  plane.set("x_axis", Value(Value::Array{0.0, 1.0, 0.0}));
  plane.set("y_axis", Value(Value::Array{0.0, 0.0, 1.0}));
  Sketch s = make_sketch_rsketch("mixed_yz", plane);
  s = add_point_rsketch(s, "left", -2.0, 0.0);
  s = add_point_rsketch(s, "right", 2.0, 0.0);
  s = add_point_rsketch(s, "center", 0.0, 0.0);
  s = add_arc_rsketch(s, "upper", "right", "left", "center");
  s = add_bspline_rsketch(s, "lower", "left", "right",
                          {SketchControlPoint("left"), SketchControlPoint(-1.0, -1.5), SketchControlPoint(1.0, -1.5), SketchControlPoint("right")},
                          3, std::vector<Scalar>{0.0, 1.0}, std::vector<int>{4, 4});
  const Face face = make_face_from_sketch_rface(s);
  const Vec3 normal = face.normal_at();
  CHECK(normal.x == doctest::Approx(1.0));
  CHECK(normal.y == doctest::Approx(0.0).epsilon(1e-6));
  for (const Vertex& vertex : face.edges().at(0).vertices()) CHECK(vertex.coordinates().x == doctest::Approx(10.0));
  CHECK(s.entities().at("lower").data.find("control_points")->as_array()[0].find("point_id")->as_string() == "left");
}

TEST_CASE("a closed rational B-spline with one seam point promotes to the exact circle") {
  const double w = std::sqrt(0.5);
  const std::vector<std::pair<double, double>> poles{{1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}, {1, 0}};
  std::vector<SketchControlPoint> control;
  for (const auto& [x, y] : poles) control.emplace_back(x, y);
  Sketch s = add_point_rsketch(make_sketch_rsketch("closed-rational"), "seam", 1.0, 0.0);
  s = add_bspline_rsketch(s, "boundary", "seam", "seam", control, 2, std::vector<Scalar>{0, 0.25, 0.5, 0.75, 1},
                          std::vector<int>{3, 2, 2, 2, 3}, std::vector<Scalar>{1, w, 1, w, 1, w, 1, w, 1});
  const Face face = make_face_from_sketch_rface(s);
  CHECK(mass(face) == doctest::Approx(kPi).epsilon(1e-9));
}

TEST_CASE("ellipse promotion") {
  Sketch s = make_sketch_rsketch("oval");
  s = add_point_rsketch(s, "c", 0.0, 0.0);
  s = add_point_rsketch(s, "M", 4.0, 0.0);
  s = add_point_rsketch(s, "m", 0.0, 2.0);
  s = add_ellipse_rsketch(s, "oval", "c", "M", "m");
  CHECK(make_face_from_sketch_rface(s).area() == doctest::Approx(kPi * 8.0).epsilon(1e-6));
  Sketch bad = add_point_rsketch(add_point_rsketch(add_point_rsketch(make_sketch_rsketch("bad"), "c", 0, 0), "M", 0, 0), "m", 0, 1);
  CHECK_THROWS_AS((void)add_ellipse_rsketch(bad, "oval", "c", "M", "m"), Error);
}

TEST_CASE("operations are recorded with the Python names") {
  CapturingRecorder recorder;
  RecorderScope scope(&recorder);
  Sketch s = make_sketch_rsketch("rec");
  s = add_point_rsketch(s, "a", 0, 0);
  s = add_point_rsketch(s, "b", 1, 0);
  s = add_line_rsketch(s, "l", "a", "b");
  s = constrain_horizontal_rsketch(s, "l");
  s = constrain_connect_rsketch(s, "a", "a");
  (void)make_wire_from_sketch_rwire(s);
  const std::vector<std::string> expected{"make_sketch_rsketch", "add_point_rsketch", "add_point_rsketch", "add_line_rsketch",
                                           "make_constrain_horizontal_rsketch", "make_constrain_coincident_rsketch", "make_wire_from_sketch_rwire"};
  CHECK(recorder.ops == expected);
  CHECK(recorder.output_counts.back() == 1);
}

namespace {
class OffsetBackend final : public SketchSolverBackend {
 public:
  std::string name() const override { return "test-offset"; }
  std::string version() const override { return "1"; }
  SketchSolveResult solve(const Sketch& sketch, const SketchSolverOptions& options) const override {
    last_tolerance = options.tolerance;
    SketchSolveResult result;
    result.sketch_id = sketch.sketch_id();
    result.status = "underconstrained";
    result.dof = 2;
    result.solved_points.set("p", {3.0, 4.0});
    result.backend = name();
    result.backend_version = version();
    return result;
  }
  mutable double last_tolerance = 0;
};
}  // namespace

TEST_CASE("backends are pluggable and the default is the native solver") {
  CHECK(get_default_sketch_solver_backend()->name() == "scad-native");
  const auto backend = std::make_shared<OffsetBackend>();
  register_sketch_solver_backend(backend);
  CHECK_THROWS_AS(register_sketch_solver_backend(backend), ValueError);
  CHECK_THROWS_AS((void)get_sketch_solver_backend("nope"), ValueError);

  Sketch s = add_point_rsketch(make_sketch_rsketch("custom"), "p", 0.0, 0.0);
  Sketch working = s;
  const SketchSolveResult result = working.solve({.strict = false, .backend = get_sketch_solver_backend("test-offset")});
  CHECK(result.solved_points.at("p") == SketchPoint2{3.0, 4.0});
  CHECK(result.backend == "test-offset");
  CHECK(backend->last_tolerance == 1e-7);
  CHECK(s.entities().at("p").data.find("x")->as_double() == 0.0);

  {
    ScopedSketchSolverBackend scoped("test-offset");
    CHECK(get_default_sketch_solver_backend()->name() == "test-offset");
  }
  CHECK(get_default_sketch_solver_backend()->name() == "scad-native");
}
