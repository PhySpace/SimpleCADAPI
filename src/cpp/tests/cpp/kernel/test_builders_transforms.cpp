#include "doctest.h"

#include <BRepBuilderAPI_MakeVertex.hxx>
#include <TopoDS.hxx>
#include <gp_Pnt.hxx>

#include <algorithm>
#include <set>
#include <string>

#include "scad/core/error.hpp"
#include "scad/kernel/builders.hpp"
#include "scad/kernel/membership.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/kernel/transforms.hpp"

using namespace scad;
using namespace scad::kernel;

namespace {

std::set<std::string> role_names(const PrimitiveBuild& built) {
  std::set<std::string> names;
  for (const auto& witness : built.roles)
    names.insert(std::string(witness.role));
  return names;
}

// Every witness is a sub-shape of the solid that was built.
void check_roles_in_solid(const PrimitiveBuild& built) {
  SubShapeIndex index(built.solid);
  for (const auto& witness : built.roles)
    CHECK_MESSAGE(index.contains(witness.shape), witness.role);
}

}  // namespace

TEST_CASE("box: volume, corner and six named faces") {
  const PrimitiveBuild box = build_box_primitive({1, 2, 3}, 2.0, 3.0, 4.0);
  CHECK(volume(box.solid) == doctest::Approx(24.0));
  const BoundingBox bounds = bounding_box(box.solid);
  CHECK(bounds.xmin == doctest::Approx(1.0));
  CHECK(bounds.ymax == doctest::Approx(5.0));
  CHECK(bounds.zmax == doctest::Approx(7.0));
  CHECK(role_names(box) ==
        std::set<std::string>{"box.bottom", "box.top", "box.front", "box.back", "box.left", "box.right"});
  check_roles_in_solid(box);

  // OCCT's names: bottom/top are -Z/+Z; left/right are -Y/+Y; back/front are -X/+X.
  const auto centre_of = [&](std::string_view role) {
    for (const auto& w : box.roles) {
      if (w.role == role)
        return center_of_mass(w.shape);
    }
    return Vec3{};
  };
  CHECK(centre_of("box.bottom").z == doctest::Approx(3.0));
  CHECK(centre_of("box.top").z == doctest::Approx(7.0));
  CHECK(centre_of("box.left").y == doctest::Approx(2.0));
  CHECK(centre_of("box.right").y == doctest::Approx(5.0));
  CHECK(centre_of("box.back").x == doctest::Approx(1.0));
  CHECK(centre_of("box.front").x == doctest::Approx(3.0));

  CHECK(volume(make_box_solid({1, 2, 3}, 2.0, 3.0, 4.0)) == doctest::Approx(24.0));
}

TEST_CASE("a box in a turned frame") {
  // x -> +Y, z -> +Z: width runs along +Y, height along -X.
  const Axes3 frame{{0, 1, 0}, {-1, 0, 0}, {0, 0, 1}};
  const PrimitiveBuild box = build_box_primitive({10, 0, 0}, 2.0, 3.0, 4.0, frame);
  const BoundingBox bounds = bounding_box(box.solid);
  CHECK(bounds.xmin == doctest::Approx(7.0));
  CHECK(bounds.xmax == doctest::Approx(10.0));
  CHECK(bounds.ymin == doctest::Approx(0.0));
  CHECK(bounds.ymax == doctest::Approx(2.0));
  check_roles_in_solid(box);
  CHECK_THROWS_AS((void)build_box_primitive({0, 0, 0}, 1, 1, 1, Axes3{{0, 0, 0}, {0, 1, 0}, {0, 0, 1}}), ValueError);
}

TEST_CASE("cylinder: volume, three faces, three edges") {
  const PrimitiveBuild cylinder = build_cylinder_primitive({0, 0, 1}, {0, 0, 1}, 2.0, 5.0);
  CHECK(volume(cylinder.solid) == doctest::Approx(kPi * 4.0 * 5.0));
  CHECK(role_names(cylinder) == std::set<std::string>{"cylinder.start", "cylinder.end", "cylinder.side",
                                                      "cylinder.start_boundary", "cylinder.end_boundary",
                                                      "cylinder.seam"});
  check_roles_in_solid(cylinder);
  for (const auto& w : cylinder.roles) {
    if (w.role == "cylinder.start")
      CHECK(center_of_mass(w.shape).z == doctest::Approx(1.0));
    if (w.role == "cylinder.end")
      CHECK(center_of_mass(w.shape).z == doctest::Approx(6.0));
  }
  CHECK(volume(make_cylinder_solid({0, 0, 0}, {1, 0, 0}, 1.0, 2.0)) == doctest::Approx(2.0 * kPi));
}

TEST_CASE("cone: a frustum has a top face, a point does not") {
  const PrimitiveBuild frustum = build_cone_primitive({0, 0, 0}, {0, 0, 1}, 3.0, 1.0, 4.0);
  CHECK(volume(frustum.solid) == doctest::Approx(kPi * 4.0 / 3.0 * (9.0 + 3.0 + 1.0)));
  CHECK(frustum.roles.size() == 6);
  CHECK(role_names(frustum).contains("cone.end"));
  check_roles_in_solid(frustum);

  const PrimitiveBuild point = build_cone_primitive({0, 0, 0}, {0, 0, 1}, 3.0, 0.0, 4.0);
  CHECK(volume(point.solid) == doctest::Approx(kPi * 9.0 * 4.0 / 3.0));
  CHECK(point.roles.size() == 5);
  CHECK_FALSE(role_names(point).contains("cone.end"));
  CHECK(volume(make_cone_solid({0, 0, 0}, {0, 0, 1}, 3.0, 0.0, 4.0)) == doctest::Approx(kPi * 12.0));
}

TEST_CASE("sphere, and what a builder does with nonsense") {
  CHECK(volume(make_sphere_solid({1, 1, 1}, 2.0)) == doctest::Approx(4.0 / 3.0 * kPi * 8.0).epsilon(1e-6));
  CHECK_THROWS_AS((void)make_box_solid({0, 0, 0}, 0.0, 1.0, 1.0), KernelError);
  CHECK_THROWS_AS((void)make_cylinder_solid({0, 0, 0}, {0, 0, 0}, 1.0, 1.0), ValueError);
  CHECK_THROWS_AS((void)make_cone_solid({0, 0, 0}, {0, 0, 1}, -1.0, 1.0, 1.0), KernelError);
}

// ---------------------------------------------------------------------------
// transforms
// ---------------------------------------------------------------------------

TEST_CASE("translate, rotate, mirror, place") {
  const TopoDS_Solid box = make_box_solid({0, 0, 0}, 2.0, 1.0, 1.0);

  const BoundingBox moved = bounding_box(translate_shape(box, {5, 0, -1}));
  CHECK(moved.xmin == doctest::Approx(5.0));
  CHECK(moved.zmin == doctest::Approx(-1.0));

  // 90 degrees about +Z through the origin: x in [0,2] -> y in [0,2].
  const BoundingBox turned = bounding_box(rotate_shape(box, 90.0, {0, 0, 1}, {0, 0, 0}));
  CHECK(turned.xmin == doctest::Approx(-1.0));
  CHECK(turned.xmax == doctest::Approx(0.0));
  CHECK(turned.ymax == doctest::Approx(2.0));
  // Rotating about a point off the origin keeps that point fixed.
  const BoundingBox about = bounding_box(rotate_shape(box, 180.0, {0, 0, 1}, {1, 0.5, 0}));
  CHECK(about.xmin == doctest::Approx(0.0));
  CHECK(about.ymin == doctest::Approx(0.0));

  const TopoDS_Shape mirrored = mirror_shape(box, {0, 0, 0}, {1, 0, 0});
  CHECK(bounding_box(mirrored).xmax == doctest::Approx(0.0));
  CHECK(bounding_box(mirrored).xmin == doctest::Approx(-2.0));
  CHECK(volume(mirrored) == doctest::Approx(2.0));

  // local x -> global +Y, local y -> global -X: a quarter turn plus a shift.
  const BoundingBox placed = bounding_box(place_shape(box, {10, 0, 0}, {0, 1, 0}, {-1, 0, 0}, {0, 0, 1}));
  CHECK(placed.xmin == doctest::Approx(9.0));
  CHECK(placed.ymax == doctest::Approx(2.0));

  CHECK_THROWS_AS((void)rotate_shape(box, 10.0, {0, 0, 0}, {0, 0, 0}), ValueError);
  CHECK_THROWS_AS((void)mirror_shape(box, {0, 0, 0}, {0, 0, 0}), ValueError);
}

TEST_CASE("a copying transform shares nothing with its input") {
  const TopoDS_Solid box = make_box_solid({0, 0, 0}, 1.0, 1.0, 1.0);
  const gp_Trsf shift = translation_trsf({3, 0, 0});
  CHECK_FALSE(box.IsPartner(apply_transform(box, shift, /*copy=*/true)));
  CHECK(box.IsPartner(apply_transform(box, shift, /*copy=*/false)));
}

TEST_CASE("a vertex can be transformed too") {
  const TopoDS_Vertex vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(1, 2, 3)).Vertex();
  const Vec3 point = vertex_point(TopoDS::Vertex(translate_shape(vertex, {1, 1, 1})));
  CHECK(point.x == doctest::Approx(2.0));
  CHECK(point.z == doctest::Approx(4.0));
}
