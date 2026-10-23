// Shape type names and checked down-casts on raw OCCT shapes (ocp_cast.py).
#pragma once

#include <string>
#include <string_view>

#include <TopoDS_Compound.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>

namespace scad::kernel {

// "vertex" | "edge" | "wire" | "face" | "shell" | "solid" | "compound" |
// "compsolid" | "shape" (an unspecified/null shape).
std::string_view shape_type_name(const TopoDS_Shape& shape) noexcept;

// Exact casts: the shape must already be of that type, otherwise a KernelError
// of class Standard_TypeMismatch (what TopoDS::X raises in the Python SDK).
TopoDS_Vertex as_vertex(const TopoDS_Shape& shape);
TopoDS_Edge as_edge(const TopoDS_Shape& shape);
TopoDS_Wire as_wire(const TopoDS_Shape& shape);
TopoDS_Face as_face(const TopoDS_Shape& shape);

// Lenient casts: a compound/solid that wraps one is accepted and its first
// shell/solid (in TopExp_Explorer order) is returned.  ValueError when there is none.
TopoDS_Shell as_shell(const TopoDS_Shape& shape);
TopoDS_Solid as_solid(const TopoDS_Shape& shape);
// Compounds only; ValueError otherwise.
TopoDS_Compound as_compound(const TopoDS_Shape& shape);

// as_solid without the exception: false when the shape holds no solid.
bool first_solid(const TopoDS_Shape& shape, TopoDS_Solid& out);

}  // namespace scad::kernel
