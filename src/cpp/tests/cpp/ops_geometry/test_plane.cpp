// The plane helpers other areas build on, and the float-or-expression arithmetic.
#include "support.hpp"

#include "scad/ops/geometry/params.hpp"
#include "scad/ops/geometry/plane.hpp"
#include "scad/ops/geometry/scalar_math.hpp"
#include "scad/reactive/expr.hpp"

using namespace scad;
using namespace scad::geometry_test;

namespace {

bool close_to(const Vec3& a, const Vec3& b, double tol = 1e-12) { return (a - b).norm() <= tol; }

}  // namespace

TEST_CASE("a +Z normal gives exactly the global frame (test_plane_axes_convention)") {
  const PlaneAxes axes = orthonormal_plane_axes({0, 0, 1});
  CHECK(close_to(axes.z_axis, {0, 0, 1}));
  CHECK(close_to(axes.x_axis, {1, 0, 0}));
  CHECK(close_to(axes.y_axis, {0, 1, 0}));
}

TEST_CASE("plane frames are unit, right-handed and transverse") {
  for (const Vec3& normal : {Vec3{0.3, -0.4, 0.86}, Vec3{1, 0, 0}, Vec3{0, 1, 0}, Vec3{0, 0, -1}, Vec3{0.2, 0.98, 0.05}}) {
    const PlaneAxes a = orthonormal_plane_axes(normal);
    CHECK(a.z_axis.norm() == doctest::Approx(1.0));
    CHECK(a.x_axis.norm() == doctest::Approx(1.0));
    CHECK(a.y_axis.norm() == doctest::Approx(1.0));
    CHECK(a.x_axis.dot(a.z_axis) == doctest::Approx(0.0).epsilon(1e-9));
    CHECK(a.y_axis.dot(a.z_axis) == doctest::Approx(0.0).epsilon(1e-9));
    CHECK(close_to(a.x_axis.cross(a.y_axis), a.z_axis));
  }
  CHECK_THROWS_AS(orthonormal_plane_axes({0, 0, 0}), ValueError);
}

TEST_CASE("default_plane_x_direction is OpenCASCADE's") {
  CHECK(close_to(default_plane_x_direction({0, 0, 1}), {1, 0, 0}));
  CHECK(close_to(default_plane_x_direction({1, 0, 0}), {0, 0, 1}));
  CHECK_THROWS(default_plane_x_direction({0, 0, 0}));
}

TEST_CASE("sketch_plane_in_current_coordinates reads named and mapped planes") {
  const PlaneFrame xz = sketch_plane_in_current_coordinates(Value("xz"));
  CHECK(close_to(xz.x_axis, {1, 0, 0}));
  CHECK(close_to(xz.y_axis, {0, 0, 1}));
  CHECK_THROWS_AS(sketch_plane_in_current_coordinates(Value("AB")), ValueError);

  const Workplane plane({0, 0, 5}, {0, 0, 1}, {1, 0, 0});
  CoordinateSystemScope scope(plane.cs());
  Value mapping = Value::object();
  mapping.set("origin", Value(Value::Array{Value(1.0), Value(0.0), Value(0.0)}));
  const PlaneFrame frame = sketch_plane_in_current_coordinates(mapping);
  CHECK(close_to(frame.origin, {1, 0, 5}));
  CHECK(close_to(frame.y_axis, {0, 1, 0}));
}

TEST_CASE("Num is a float until an operand is symbolic, like Python") {
  const Num literal = (Num(3.0) + Num(2.0) * Num(4.0)) / Num(2.0);
  CHECK_FALSE(literal.symbolic());
  CHECK(literal.literal() == 5.5);
  CHECK((-Num(2.0)).literal() == -2.0);

  const reactive::Sym w = reactive::make_var("w", 10.0);
  const Num mixed = Num(1.0) + Num(w.scalar()) * Num(0.5);
  REQUIRE(mixed.symbolic());
  CHECK(mixed.scalar().value() == 6.0);
  // The same expression built twice has one identity.
  const Num again = Num(1.0) + Num(w.scalar()) * Num(0.5);
  CHECK(reactive::scalar_node(mixed.scalar())->expr_id() == reactive::scalar_node(again.scalar())->expr_id());
}

TEST_CASE("OpParams stores evaluated numbers and notes the symbolic ones by path") {
  const reactive::Sym w = reactive::make_var("w", 10.0);
  Scalar3 centre{Scalar(1.0), w.scalar(), Scalar(3.0)};
  OpRecord record = OpParams("demo", primitive_labels("edge"))
                        .scalar("radius", w.scalar())
                        .point("center", centre)
                        .coordinates("poles", {{Scalar(0.0), Scalar(1.0)}, {Scalar(2.0), w.scalar()}})
                        .optional_scalars("weights", std::nullopt)
                        .boolean("periodic", false)
                        .take();
  CHECK(record.op == "demo");
  CHECK(record.labels == std::vector<std::string>{"edge", "primitive"});
  CHECK(record.params.dump() == R"({"radius":10,"center":[1,10,3],"poles":[[0,1],[2,10]],"weights":null,"periodic":false})");
  std::vector<std::string> paths;
  for (const auto& [path, scalar] : record.symbolic) paths.push_back(path);
  CHECK(paths == std::vector<std::string>{"radius", "center[1]", "poles[1][1]"});
  CHECK(derived_labels("face") == std::vector<std::string>{"derived", "face"});
}
