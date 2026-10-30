#include "doctest.h"

#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"

using namespace scad;

TEST_CASE("measurements of a box at an offset") {
  const TopoDS_Shape box = BRepPrimAPI_MakeBox(gp_Pnt(1, 2, 3), 2.0, 4.0, 6.0).Solid();
  CHECK(kernel::volume(box) == doctest::Approx(48.0));
  const Vec3 c = kernel::center_of_mass(box);
  CHECK(c.x == doctest::Approx(2.0));
  CHECK(c.y == doctest::Approx(4.0));
  CHECK(c.z == doctest::Approx(6.0));
  const auto bb = kernel::bounding_box(box);
  CHECK(bb.xlen() == doctest::Approx(2.0));
  CHECK(bb.ylen() == doctest::Approx(4.0));
  CHECK(bb.zlen() == doctest::Approx(6.0));
}

TEST_CASE("a sphere's volume uses knot-span integration") {
  const TopoDS_Shape sphere = BRepPrimAPI_MakeSphere(2.0).Solid();
  CHECK(kernel::volume(sphere) == doctest::Approx(4.0 / 3.0 * kPi * 8.0).epsilon(1e-6));
}

TEST_CASE("distance between separated boxes") {
  const TopoDS_Shape a = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Solid();
  const TopoDS_Shape b = BRepPrimAPI_MakeBox(gp_Pnt(4, 0, 0), 1.0, 1.0, 1.0).Solid();
  CHECK(kernel::distance(a, b) == doctest::Approx(3.0));
}

TEST_CASE("center_of_mass of a null shape is a ValueError, not a crash") {
  CHECK_THROWS_AS(kernel::center_of_mass(TopoDS_Shape()), ValueError);
}

TEST_CASE("traversal orderings: outer wire excluded from inner wires") {
  const TopoDS_Shape box = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Solid();
  const auto faces = kernel::faces_of(box);
  REQUIRE(faces.size() == 6);
  CHECK(kernel::wires_of(faces[0]).size() == 1);
  CHECK(kernel::inner_wires_of(faces[0]).empty());
  CHECK(kernel::edges_of(box).size() == 24);     // 12 edges, each used by two faces
  CHECK(kernel::vertices_of(box).size() == 48);  // 6 faces x 4 edges x 2 vertex uses
}
