#include "doctest.h"

#include <cmath>

#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"

using namespace scad;

TEST_CASE("Vec3 arithmetic") {
  const Vec3 a{1, 2, 3}, b{4, 5, 6};
  CHECK((a + b) == Vec3{5, 7, 9});
  CHECK(a.dot(b) == doctest::Approx(32.0));
  CHECK(a.cross(b) == Vec3{-3, 6, -3});
  CHECK(Vec3{3, 4, 0}.norm() == doctest::Approx(5.0));
  CHECK(Vec3{}.normalized() == Vec3{});
}

TEST_CASE("CoordinateSystem derives z from x cross y and does not re-orthogonalize") {
  const CoordinateSystem cs({1, 2, 3}, {2, 0, 0}, {0, 3, 0});
  CHECK(cs.x_axis() == Vec3{1, 0, 0});
  CHECK(cs.y_axis() == Vec3{0, 1, 0});
  CHECK(cs.z_axis() == Vec3{0, 0, 1});
  CHECK(cs.transform_point({1, 1, 1}) == Vec3{2, 3, 4});
  CHECK(cs.transform_vector({1, 1, 1}) == Vec3{1, 1, 1});
}

TEST_CASE("CoordinateSystem rejects zero axes with structured guidance") {
  try {
    CoordinateSystem({0, 0, 0}, {0, 0, 0}, {0, 1, 0});
    FAIL("expected an Error");
  } catch (const Error& e) {
    CHECK(e.operation() == "CoordinateSystem._normalize");
    CHECK(std::string(e.what()).find("What happened:") != std::string::npos);
  }
}

TEST_CASE("Workplane stacks and unwinds") {
  CHECK(current_cs().origin() == Vec3{0, 0, 0});
  {
    Workplane wp({0, 0, 5}, {0, 0, 1});
    wp.enter();
    CHECK(current_cs().origin() == Vec3{0, 0, 5});
    {
      Workplane inner({1, 0, 0}, {0, 0, 1});
      inner.enter();
      CHECK(current_cs().origin() == Vec3{1, 0, 5});
      inner.exit();
    }
    CHECK(current_cs().origin() == Vec3{0, 0, 5});
    wp.exit();
  }
  CHECK(current_cs().origin() == Vec3{0, 0, 0});
}

TEST_CASE("Scalar rejects non-finite values") {
  CHECK(evaluate_scalar(3.0, "w") == 3.0);
  CHECK_THROWS_AS(evaluate_scalar(std::nan(""), "w"), ValueError);
}

TEST_CASE("Value keeps object insertion order and dumps JSON") {
  Value v = Value::object();
  v.set("b", 1);
  v.set("a", "x");
  v.set("b", 2.5);
  CHECK(v.dump() == R"({"b":2.5,"a":"x"})");
  CHECK(Value(1) == Value(1.0));
}
