#include "doctest.h"

#include <BRepPrimAPI_MakeBox.hxx>
#include <TopoDS.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/builders.hpp"
#include "scad/kernel/cast.hpp"
#include "scad/kernel/membership.hpp"
#include "scad/kernel/topology.hpp"

using namespace scad;
using namespace scad::kernel;

namespace {
TopoDS_Solid unit_box(double x = 0) {
  return make_box_solid({x, 0, 0}, 1, 1, 1);
}
}  // namespace

TEST_CASE("shape_type_name names every kind") {
  const TopoDS_Solid box = unit_box();
  CHECK(shape_type_name(box) == "solid");
  CHECK(shape_type_name(faces_of(box).front()) == "face");
  CHECK(shape_type_name(edges_of(box).front()) == "edge");
  CHECK(shape_type_name(vertices_of(box).front()) == "vertex");
  CHECK(shape_type_name(outer_wire_of(faces_of(box).front())) == "wire");
  CHECK(shape_type_name(TopoDS_Shape()) == "shape");
}

TEST_CASE("exact casts check the type; lenient casts look inside") {
  const TopoDS_Solid box = unit_box();
  const TopoDS_Face face = faces_of(box).front();
  CHECK(as_face(face).IsSame(face));
  CHECK_THROWS_AS((void)as_edge(face), KernelError);
  CHECK_THROWS_AS((void)as_vertex(box), KernelError);
  CHECK_THROWS_AS((void)as_wire(face), KernelError);
  try {
    (void)as_edge(face);
  } catch (const KernelError& e) {
    CHECK(e.occt_class() == "Standard_TypeMismatch");
  }

  // A solid is its own solid; a compound hands over its first.
  CHECK(as_solid(box).IsSame(box));
  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);
  builder.Add(compound, unit_box(5));
  builder.Add(compound, box);
  const TopoDS_Solid first = as_solid(compound);
  CHECK(first.IsSame(solids_of(compound).front()));

  CHECK_THROWS_AS((void)as_solid(face), ValueError);
  CHECK_THROWS_AS((void)as_solid(TopoDS_Shape()), ValueError);
  CHECK_THROWS_AS((void)as_compound(box), ValueError);
  CHECK(as_compound(compound).IsSame(compound));
  CHECK(shape_type_name(as_shell(box)) == "shell");
  CHECK_THROWS_AS((void)as_shell(face), ValueError);

  TopoDS_Solid out;
  CHECK(first_solid(compound, out));
  CHECK_FALSE(first_solid(face, out));
}

TEST_CASE("SubShapeIndex answers membership by identity") {
  const TopoDS_Solid box = unit_box();
  const TopoDS_Solid other = unit_box(5);
  SubShapeIndex index(box);

  CHECK(index.contains(box));
  CHECK(index.contains(box.Reversed()));
  for (const TopoDS_Face& face : faces_of(box)) {
    CHECK(index.contains(face));
    CHECK(index.contains(face.Reversed()));
  }
  for (const TopoDS_Edge& edge : edges_of(box))
    CHECK(index.contains(edge));
  for (const TopoDS_Face& face : faces_of(other))
    CHECK_FALSE(index.contains(face));
  CHECK_FALSE(index.contains(other));
  CHECK_FALSE(index.contains(TopoDS_Shape()));

  CHECK(index.of_type(TopAbs_FACE).Extent() == 6);
  CHECK(index.of_type(TopAbs_EDGE).Extent() == 12);
  CHECK(index.of_type(TopAbs_VERTEX).Extent() == 8);
  CHECK(index.of_type(TopAbs_SOLID).Extent() == 1);

  // A shape of a higher kind than the root can never be below it.
  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);
  builder.Add(compound, box);
  CHECK_FALSE(index.contains(compound));
  CHECK(SubShapeIndex(compound).contains(box));
  CHECK(SubShapeIndex(compound).contains(faces_of(box).front()));
}
