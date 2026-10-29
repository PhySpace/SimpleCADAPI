// translate, rotate, mirror, scale, transform and the patterns.
#include "fixtures.hpp"

using namespace scad;
using namespace scad::feature_test;
using doctest::Approx;

namespace {

Solid tagged_box() {
  return box(2, 3, 4);
}

}  // namespace

TEST_CASE("translate moves the solid and records the track summary") {
  const Solid cube = tagged_box();
  const Solid moved(translate_shape(cube, scalar3(1, 2, 3)));
  CHECK(moved.volume() == Approx(24.0));
  CHECK(moved.bounding_box().zmin == Approx(3.0));
  CHECK(moved.get_metadata("track").find("op")->as_string() == "make_translate_rshape");
}

TEST_CASE("rotate, mirror and the zero rotation") {
  const Solid cube = tagged_box();
  const Solid turned(rotate_shape(cube, 90.0, scalar3(0, 0, 1)));
  CHECK(turned.bounding_box().xlen() == Approx(3.0));
  CHECK(rotate_shape(cube, 0.0).same_entity(cube));

  const Solid mirrored(mirror_shape(cube, scalar3(0, 0, 0), scalar3(1, 0, 0)));
  CHECK(mirrored.volume() == Approx(24.0));
  CHECK(has_tag(mirrored, "solid.transform.mirrored"));
  CHECK_THROWS_AS((void)mirror_shape(cube, scalar3(0, 0, 0), scalar3(0, 0, 0)), Error);
  CHECK(failure_of([&] { (void)rotate_shape(cube, 30.0, scalar3(0, 0, 0)); }).operation() == "rotate_shape");
}

TEST_CASE("faces and wires move too") {
  const Face face = make_rectangle_rface(2, 1);
  const Shape moved = translate_shape(face, scalar3(1, 2, 3));
  CHECK(moved.kind() == Kind::Face);
  CHECK(moved.center().z == Approx(3.0));
  CHECK(rotate_shape(make_rectangle_rwire(2, 1), 90.0).kind() == Kind::Wire);
}

TEST_CASE("scale and affine transform") {
  const Solid body = box(10, 12, 14);
  CHECK(scale_rsolid(body, scalar3(2, 2, 2)).volume() == Approx(8 * 1680.0));
  CHECK(scale_rsolid(body, scalar3(2, 3, 0.5), scalar3(5, 6, 7)).volume() == Approx(3 * 1680.0));
  const std::vector<std::vector<Scalar>> shear{{1, 0.3, 0, 5}, {0, 1, 0, 2}, {0, 0, 1, 0}, {0, 0, 0, 1}};
  CHECK(transform_rsolid(body, shear).volume() == Approx(1680.0));
  CHECK_THROWS_AS((void)scale_rsolid(body, scalar3(0, 1, 1)), ValueError);
  const std::vector<std::vector<Scalar>> singular(4, std::vector<Scalar>(4, Scalar(0.0)));
  CHECK_THROWS_AS((void)transform_rsolid(body, singular), ValueError);
  const std::vector<std::vector<Scalar>> perspective{{1, 0, 0, 0}, {0, 1, 0, 0}, {0, 0, 1, 0}, {0, 0, 1, 1}};
  CHECK_THROWS_AS((void)transform_rsolid(body, perspective), ValueError);
}

TEST_CASE("patterns number their members") {
  const Solid tiny = box(0.5, 0.5, 0.5);
  const std::vector<Shape> row = linear_pattern_rsolidlist(tiny, scalar3(1, 0, 0), 5, 1.0);
  REQUIRE(row.size() == 5);
  CHECK(row[4].center().x == Approx(4.0));
  CHECK(has_tag(row[2], "solid.pattern.linear"));
  CHECK(row[2].get_metadata("geo").find("pattern")->find("index")->as_int() == 3);

  const Solid arm = box(0.2, 0.2, 1.0, scalar3(2, 0, 0));
  const std::vector<Shape> ring = radial_pattern_rsolidlist(arm, scalar3(0, 0, 0), scalar3(0, 0, 1), 6, 360.0);
  REQUIRE(ring.size() == 6);
  CHECK(has_tag(ring[5], "solid.pattern.radial"));

  CHECK(failure_of([&] { (void)linear_pattern_rsolidlist(tiny, scalar3(1, 0, 0), 0, 1.0); }).operation() ==
        "linear_pattern_rsolidlist");
  CHECK(failure_of([&] {
          (void)radial_pattern_rsolidlist(arm, scalar3(0, 0, 0), scalar3(0, 0, 1), 3, 0.0);
        }).operation() == "radial_pattern_rsolidlist");
}
