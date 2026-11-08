// convert_to_bspline_redge / convert_to_bspline_rface: the explicit step that turns analytic geometry into the
// B-splines the edits work on (BRepBuilderAPI_NurbsConvert), and inspect_curve_rcurvedata /
// inspect_surface_rsurfacedata, which report what an edit would work on.
#include <cmath>

#include <BRepBuilderAPI_NurbsConvert.hxx>
#include <BRepTools.hxx>
#include <BRepTools_History.hxx>
#include <BRep_Tool.hxx>
#include <Geom2d_Curve.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>

#include "access.hpp"
#include "finish.hpp"
#include "scad/surface/editing.hpp"

namespace scad {

using namespace surface::editing;

namespace {

struct Converted {
  TopoDS_Shape shape;
  BRepTools_History history;
};

Converted nurbs_convert(const TopoDS_Shape& input, const char* what) {
  BRepBuilderAPI_NurbsConvert converter(input, Standard_True);
  if (!converter.IsDone() || converter.Shape().IsNull())
    throw ValueError(std::string("the kernel could not convert the ") + what + " to a B-spline");
  TopTools_ListOfShape arguments;
  arguments.Append(input);
  return {converter.Shape(), BRepTools_History(arguments, converter)};
}

TopoDS_Shape first_of(const TopoDS_Shape& shape, TopAbs_ShapeEnum type) {
  TopExp_Explorer it(shape, type);
  if (!it.More())
    throw ValueError("the converted shape is empty");
  return it.Current();
}

// A face is trimmed when its boundary is not the natural boundary of its surface's domain: more than one loop, (u, v)
// bounds inside the domain, or a loop edge that does not run along one side of the domain (u or v constant at a
// domain bound; a seam of a periodic surface is such a side too).  Judged on samples of the pcurves, so a side that a
// converter turned into a 2D B-spline still counts as a side.
bool is_trimmed(const TopoDS_Face& face, const Handle(Geom_Surface) & surface) {
  int wires = 0;
  for (TopExp_Explorer it(face, TopAbs_WIRE); it.More(); it.Next())
    ++wires;
  if (wires != 1)
    return true;
  double u1 = 0, u2 = 0, v1 = 0, v2 = 0, fu1 = 0, fu2 = 0, fv1 = 0, fv2 = 0;
  surface->Bounds(u1, u2, v1, v2);
  BRepTools::UVBounds(face, fu1, fu2, fv1, fv2);
  constexpr double kTol = 1e-7;
  if (std::abs(fu1 - u1) > kTol || std::abs(fu2 - u2) > kTol || std::abs(fv1 - v1) > kTol || std::abs(fv2 - v2) > kTol)
    return true;
  for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
    double first = 0, last = 0;
    const Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(TopoDS::Edge(it.Current()), face, first, last);
    if (pcurve.IsNull())
      return true;
    bool on[4] = {true, true, true, true};  // u = u1, u = u2, v = v1, v = v2 at every sample
    for (int i = 0; i <= 8; ++i) {
      const gp_Pnt2d uv = pcurve->Value(first + (last - first) * i / 8.0);
      on[0] = on[0] && std::abs(uv.X() - u1) <= kTol;
      on[1] = on[1] && std::abs(uv.X() - u2) <= kTol;
      on[2] = on[2] && std::abs(uv.Y() - v1) <= kTol;
      on[3] = on[3] && std::abs(uv.Y() - v2) <= kTol;
    }
    if (!(on[0] || on[1] || on[2] || on[3]))
      return true;
  }
  return false;
}

Value range_value(double a, double b) {
  return Value(Value::Array{a, b});
}

}  // namespace

Edge convert_to_bspline_redge(const Edge& edge, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec{"convert_to_bspline_redge",
                               "Failed to convert the edge's curve to a B-spline.",
                               {"The edge is degenerated or the kernel refused the conversion."},
                               {"Pass an edge that has a 3D curve."}};
  return edit_scope(kSpec, [&] {
    if (edge.wrapped().IsNull())
      throw ValueError("edge must not be null");
    (void)curve_rep(TopoDS::Edge(edge.wrapped()));
    const Converted c = nurbs_convert(edge.wrapped(), "edge");
    return finish_built_edge(edge, "convert_to_bspline_redge", Value::object(), tag_prefix, c.shape, c.history);
  });
}

Face convert_to_bspline_rface(const Face& face, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec{"convert_to_bspline_rface",
                               "Failed to convert the face's surface to a B-spline.",
                               {"The kernel refused the conversion of this surface."},
                               {"Pass a valid face; check it with inspect_surface_rsurfacedata."}};
  return edit_scope(kSpec, [&] {
    if (face.wrapped().IsNull())
      throw ValueError("face must not be null");
    const Converted c = nurbs_convert(face.wrapped(), "face");
    return finish_built_face(face, "convert_to_bspline_rface", Value::object(), tag_prefix, c.shape, c.history);
  });
}

Value inspect_curve_rcurvedata(const Edge& edge) {
  static const ErrorSpec kSpec{"inspect_curve_rcurvedata",
                               "Failed to read the curve of the edge.",
                               {"The edge is degenerated (it has no 3D curve)."},
                               {"Pass an edge that has a 3D curve."}};
  return edit_scope(kSpec, [&] {
    if (edge.wrapped().IsNull())
      throw ValueError("edge must not be null");
    const TopoDS_Edge e = TopoDS::Edge(edge.wrapped());
    const CurveRep rep = curve_rep(e);
    const std::string type = curve_type_name(rep.curve);
    const bool freeform = is_freeform(type);
    Handle(Geom_BSplineCurve) bspline = bspline_copy(rep.curve);
    CurveRep read = rep;
    if (bspline.IsNull()) {  // what convert_to_bspline_redge would make of it
      read = curve_rep(TopoDS::Edge(first_of(nurbs_convert(e, "edge").shape, TopAbs_EDGE)));
      bspline = bspline_copy(read.curve);
      if (bspline.IsNull())
        throw ValueError("the kernel could not convert the edge's " + type + " curve to a B-spline");
    }
    Value out = Value::object();
    out.set("type", type);
    out.set("analytic", !freeform);
    out.set("editable", freeform);
    out.set("conversion", freeform ? Value() : Value("convert_to_bspline_redge"));
    const Value data = curve_data(bspline, read.location);  // kept alive: the loop reads into it
    for (const auto& [key, value] : data.as_object())
      out.set(key, value);
    out.set("reversed", e.Orientation() == TopAbs_REVERSED);
    out.set("parameter_range", range_value(read.first, read.last));
    return out;
  });
}

Value inspect_surface_rsurfacedata(const Face& face) {
  static const ErrorSpec kSpec{"inspect_surface_rsurfacedata",
                               "Failed to read the surface of the face.",
                               {"The face has no surface or the kernel could not convert it."},
                               {"Pass a valid face."}};
  return edit_scope(kSpec, [&] {
    if (face.wrapped().IsNull())
      throw ValueError("face must not be null");
    TopoDS_Face f = TopoDS::Face(face.wrapped());
    const SurfaceRep rep = surface_rep(f);
    const std::string type = surface_type_name(rep.surface);
    const bool freeform = is_freeform(type);
    Handle(Geom_BSplineSurface) bspline = bspline_copy(rep.surface);
    SurfaceRep read = rep;
    if (bspline.IsNull()) {  // what convert_to_bspline_rface would make of it
      f = TopoDS::Face(first_of(nurbs_convert(f, "face").shape, TopAbs_FACE));
      read = surface_rep(f);
      bspline = bspline_copy(read.surface);
      if (bspline.IsNull())
        throw ValueError("the kernel could not convert the face's " + type + " surface to a B-spline");
    }
    Value out = Value::object();
    out.set("type", type);
    out.set("analytic", !freeform);
    out.set("editable", freeform);
    out.set("conversion", freeform ? Value() : Value("convert_to_bspline_rface"));
    const Value data = surface_data(bspline, read.location);  // kept alive: the loop reads into it
    for (const auto& [key, value] : data.as_object())
      out.set(key, value);
    out.set("reversed", f.Orientation() == TopAbs_REVERSED);
    out.set("trimmed", is_trimmed(f, bspline));
    double u1 = 0, u2 = 0, v1 = 0, v2 = 0;
    BRepTools::UVBounds(f, u1, u2, v1, v2);
    out.set("uv_bounds", Value(Value::Array{u1, u2, v1, v2}));
    return out;
  });
}

}  // namespace scad
