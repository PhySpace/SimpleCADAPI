#include "scad/kernel/cast.hpp"

#include <TopAbs_ShapeEnum.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>

#include "scad/core/error.hpp"

namespace scad::kernel {

namespace {

[[noreturn]] void type_mismatch(const char* what) {
  throw KernelError("Standard_TypeMismatch", what);
}

template <class T, class Cast>
T exact(const TopoDS_Shape& shape, TopAbs_ShapeEnum type, const char* what, Cast cast) {
  if (!shape.IsNull() && shape.ShapeType() != type)
    type_mismatch(what);
  return cast(shape);
}

// The first sub-shape of `type`, or the shape itself when it already is one.
bool find_first(const TopoDS_Shape& shape, TopAbs_ShapeEnum type, TopoDS_Shape& out) {
  if (shape.IsNull())
    return false;
  if (shape.ShapeType() == type) {
    out = shape;
    return true;
  }
  const TopExp_Explorer explorer(shape, type);
  if (!explorer.More())
    return false;
  out = explorer.Current();
  return true;
}

}  // namespace

std::string_view shape_type_name(const TopoDS_Shape& shape) noexcept {
  if (shape.IsNull())
    return "shape";
  switch (shape.ShapeType()) {
    case TopAbs_VERTEX:
      return "vertex";
    case TopAbs_EDGE:
      return "edge";
    case TopAbs_WIRE:
      return "wire";
    case TopAbs_FACE:
      return "face";
    case TopAbs_SHELL:
      return "shell";
    case TopAbs_SOLID:
      return "solid";
    case TopAbs_COMPSOLID:
      return "compsolid";
    case TopAbs_COMPOUND:
      return "compound";
    case TopAbs_SHAPE:
      break;
  }
  return "shape";
}

TopoDS_Vertex as_vertex(const TopoDS_Shape& shape) {
  return exact<TopoDS_Vertex>(shape, TopAbs_VERTEX, "TopoDS::Vertex",
                              [](const TopoDS_Shape& s) { return TopoDS::Vertex(s); });
}

TopoDS_Edge as_edge(const TopoDS_Shape& shape) {
  return exact<TopoDS_Edge>(shape, TopAbs_EDGE, "TopoDS::Edge", [](const TopoDS_Shape& s) { return TopoDS::Edge(s); });
}

TopoDS_Wire as_wire(const TopoDS_Shape& shape) {
  return exact<TopoDS_Wire>(shape, TopAbs_WIRE, "TopoDS::Wire", [](const TopoDS_Shape& s) { return TopoDS::Wire(s); });
}

TopoDS_Face as_face(const TopoDS_Shape& shape) {
  return exact<TopoDS_Face>(shape, TopAbs_FACE, "TopoDS::Face", [](const TopoDS_Shape& s) { return TopoDS::Face(s); });
}

TopoDS_Shell as_shell(const TopoDS_Shape& shape) {
  TopoDS_Shape found;
  if (find_first(shape, TopAbs_SHELL, found))
    return TopoDS::Shell(found);
  throw ValueError("Expected a shell-compatible OCP shape, got " + std::string(shape_type_name(shape)));
}

TopoDS_Solid as_solid(const TopoDS_Shape& shape) {
  TopoDS_Solid solid;
  if (first_solid(shape, solid))
    return solid;
  throw ValueError("Expected a solid-compatible OCP shape, got " + std::string(shape_type_name(shape)));
}

TopoDS_Compound as_compound(const TopoDS_Shape& shape) {
  if (shape.IsNull() || shape.ShapeType() != TopAbs_COMPOUND) {
    throw ValueError("Expected a compound OCP shape, got " + std::string(shape_type_name(shape)));
  }
  return TopoDS::Compound(shape);
}

bool first_solid(const TopoDS_Shape& shape, TopoDS_Solid& out) {
  TopoDS_Shape found;
  if (!find_first(shape, TopAbs_SOLID, found))
    return false;
  out = TopoDS::Solid(found);
  return true;
}

}  // namespace scad::kernel
