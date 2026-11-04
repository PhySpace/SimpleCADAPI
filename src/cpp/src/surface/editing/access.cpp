// The editable geometry behind an Edge / Face, the frames, and the plain-data views; see access.hpp.
#include "access.hpp"

#include <cmath>

#include <BRep_Tool.hxx>
#include <GeomAdaptor_Curve.hxx>
#include <GeomAdaptor_Surface.hxx>
#include <GeomConvert.hxx>
#include <Geom_BezierCurve.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TopoDS.hxx>
#include <gp_Mat.hxx>

#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"

namespace scad::surface::editing {

namespace {

Value numbers(const TColStd_Array1OfReal& values) {
  Value::Array out;
  for (int i = values.Lower(); i <= values.Upper(); ++i)
    out.emplace_back(values(i));
  return Value(std::move(out));
}

Value integers(const TColStd_Array1OfInteger& values) {
  Value::Array out;
  for (int i = values.Lower(); i <= values.Upper(); ++i)
    out.emplace_back(values(i));
  return Value(std::move(out));
}

Value range(double a, double b) {
  return Value(Value::Array{a, b});
}

}  // namespace

std::string curve_type_name(const Handle(Geom_Curve) & curve) {
  switch (GeomAdaptor_Curve(curve).GetType()) {
    case GeomAbs_Line:
      return "line";
    case GeomAbs_Circle:
      return "circle";
    case GeomAbs_Ellipse:
      return "ellipse";
    case GeomAbs_Hyperbola:
      return "hyperbola";
    case GeomAbs_Parabola:
      return "parabola";
    case GeomAbs_BezierCurve:
      return "bezier";
    case GeomAbs_BSplineCurve:
      return "bspline";
    case GeomAbs_OffsetCurve:
      return "offset";
    default:
      return "other";
  }
}

std::string surface_type_name(const Handle(Geom_Surface) & surface) {
  switch (GeomAdaptor_Surface(surface).GetType()) {
    case GeomAbs_Plane:
      return "plane";
    case GeomAbs_Cylinder:
      return "cylinder";
    case GeomAbs_Cone:
      return "cone";
    case GeomAbs_Sphere:
      return "sphere";
    case GeomAbs_Torus:
      return "torus";
    case GeomAbs_BezierSurface:
      return "bezier";
    case GeomAbs_BSplineSurface:
      return "bspline";
    case GeomAbs_SurfaceOfRevolution:
      return "revolution";
    case GeomAbs_SurfaceOfExtrusion:
      return "extrusion";
    case GeomAbs_OffsetSurface:
      return "offset";
    default:
      return "other";
  }
}

bool is_freeform(const std::string& type_name) {
  return type_name == "bspline" || type_name == "bezier";
}

CurveRep curve_rep(const TopoDS_Edge& edge) {
  CurveRep rep;
  rep.curve = BRep_Tool::Curve(edge, rep.location, rep.first, rep.last);
  if (rep.curve.IsNull())
    throw ValueError("the edge has no 3D curve (a degenerated edge)");
  return rep;
}

SurfaceRep surface_rep(const TopoDS_Face& face) {
  SurfaceRep rep;
  rep.surface = BRep_Tool::Surface(face, rep.location);
  if (rep.surface.IsNull())
    throw ValueError("the face has no surface");
  return rep;
}

Handle(Geom_BSplineCurve) bspline_copy(const Handle(Geom_Curve) & curve) {
  Handle(Geom_Curve) basis = curve;
  while (const Handle(Geom_TrimmedCurve) trimmed = Handle(Geom_TrimmedCurve)::DownCast(basis))
    basis = trimmed->BasisCurve();
  if (const Handle(Geom_BSplineCurve) bspline = Handle(Geom_BSplineCurve)::DownCast(basis))
    return Handle(Geom_BSplineCurve)::DownCast(bspline->Copy());
  if (const Handle(Geom_BezierCurve) bezier = Handle(Geom_BezierCurve)::DownCast(basis))
    return GeomConvert::CurveToBSplineCurve(Handle(Geom_BezierCurve)::DownCast(bezier->Copy()));
  return {};
}

Handle(Geom_BSplineSurface) bspline_copy(const Handle(Geom_Surface) & surface) {
  Handle(Geom_Surface) basis = surface;
  while (const Handle(Geom_RectangularTrimmedSurface) trimmed = Handle(Geom_RectangularTrimmedSurface)::DownCast(basis))
    basis = trimmed->BasisSurface();
  if (const Handle(Geom_BSplineSurface) bspline = Handle(Geom_BSplineSurface)::DownCast(basis))
    return Handle(Geom_BSplineSurface)::DownCast(bspline->Copy());
  if (const Handle(Geom_BezierSurface) bezier = Handle(Geom_BezierSurface)::DownCast(basis))
    return GeomConvert::SurfaceToBSplineSurface(Handle(Geom_BezierSurface)::DownCast(bezier->Copy()));
  return {};
}

EditableCurve editable_curve(const Edge& edge) {
  if (edge.wrapped().IsNull())
    throw ValueError("edge must not be null");
  const CurveRep rep = curve_rep(TopoDS::Edge(edge.wrapped()));
  const Handle(Geom_BSplineCurve) copy = bspline_copy(rep.curve);
  if (copy.IsNull())
    throw ValueError("the edge carries a " + curve_type_name(rep.curve) +
                     " curve, not a B-spline; convert it explicitly with convert_to_bspline_redge first");
  return {copy, rep.location, rep.first, rep.last};
}

EditableSurface editable_surface(const Face& face) {
  if (face.wrapped().IsNull())
    throw ValueError("face must not be null");
  const SurfaceRep rep = surface_rep(TopoDS::Face(face.wrapped()));
  const Handle(Geom_BSplineSurface) copy = bspline_copy(rep.surface);
  if (copy.IsNull())
    throw ValueError("the face carries a " + surface_type_name(rep.surface) +
                     " surface, not a B-spline; convert it explicitly with convert_to_bspline_rface first");
  return {copy, rep.location};
}

// ---- frames ------------------------------------------------------------------------------------------------------
gp_Pnt rep_point(const Vec3& user, const TopLoc_Location& location) {
  const Vec3 world = current_cs().transform_point(user);
  return gp_Pnt(world.x, world.y, world.z).Transformed(location.Transformation().Inverted());
}

namespace {

// global -> local of the current coordinate system: the inverse of [x y z] (y is not re-orthogonalised there).
Vec3 to_user(const Vec3& world, bool is_point) {
  const CoordinateSystem& cs = current_cs();
  const Vec3 d = is_point ? world - cs.origin() : world;
  const gp_Mat basis(gp_XYZ(cs.x_axis().x, cs.x_axis().y, cs.x_axis().z),
                     gp_XYZ(cs.y_axis().x, cs.y_axis().y, cs.y_axis().z),
                     gp_XYZ(cs.z_axis().x, cs.z_axis().y, cs.z_axis().z));
  gp_XYZ local(d.x, d.y, d.z);
  local.Multiply(basis.Inverted());
  return {local.X(), local.Y(), local.Z()};
}

}  // namespace

Vec3 user_point(const gp_Pnt& rep, const TopLoc_Location& location) {
  const gp_Pnt world = rep.Transformed(location.Transformation());
  return to_user({world.X(), world.Y(), world.Z()}, true);
}

Vec3 user_vector(const gp_Vec& rep, const TopLoc_Location& location) {
  const gp_Vec world = rep.Transformed(location.Transformation());
  return to_user({world.X(), world.Y(), world.Z()}, false);
}

void require_finite(const Vec3& point, const std::string& label) {
  if (!point.is_finite())
    throw ValueError(label + " must contain finite coordinates");
}

// ---- plain data --------------------------------------------------------------------------------------------------
Value point_value(const Vec3& point) {
  return Value(Value::Array{point.x, point.y, point.z});
}

Value curve_data(const Handle(Geom_BSplineCurve) & curve, const TopLoc_Location& location) {
  Value out = Value::object();
  out.set("degree", curve->Degree());
  Value::Array poles, weights;
  for (int i = 1; i <= curve->NbPoles(); ++i) {
    poles.push_back(point_value(user_point(curve->Pole(i), location)));
    weights.emplace_back(curve->Weight(i));
  }
  out.set("poles", Value(std::move(poles)));
  out.set("weights", Value(std::move(weights)));
  out.set("knots", numbers(curve->Knots()));
  out.set("multiplicities", integers(curve->Multiplicities()));
  out.set("periodic", static_cast<bool>(curve->IsPeriodic()));
  out.set("rational", static_cast<bool>(curve->IsRational()));
  out.set("closed", static_cast<bool>(curve->IsClosed()));
  out.set("domain", range(curve->FirstParameter(), curve->LastParameter()));
  return out;
}

Value surface_data(const Handle(Geom_BSplineSurface) & surface, const TopLoc_Location& location) {
  Value out = Value::object();
  out.set("u_degree", surface->UDegree());
  out.set("v_degree", surface->VDegree());
  Value::Array poles, weights;
  for (int i = 1; i <= surface->NbUPoles(); ++i) {
    Value::Array pole_row, weight_row;
    for (int j = 1; j <= surface->NbVPoles(); ++j) {
      pole_row.push_back(point_value(user_point(surface->Pole(i, j), location)));
      weight_row.emplace_back(surface->Weight(i, j));
    }
    poles.emplace_back(std::move(pole_row));
    weights.emplace_back(std::move(weight_row));
  }
  out.set("poles", Value(std::move(poles)));
  out.set("weights", Value(std::move(weights)));
  out.set("u_knots", numbers(surface->UKnots()));
  out.set("v_knots", numbers(surface->VKnots()));
  out.set("u_multiplicities", integers(surface->UMultiplicities()));
  out.set("v_multiplicities", integers(surface->VMultiplicities()));
  out.set("u_periodic", static_cast<bool>(surface->IsUPeriodic()));
  out.set("v_periodic", static_cast<bool>(surface->IsVPeriodic()));
  out.set("rational", static_cast<bool>(surface->IsURational() || surface->IsVRational()));
  double u1 = 0, u2 = 0, v1 = 0, v2 = 0;
  surface->Bounds(u1, u2, v1, v2);
  out.set("domain", Value(Value::Array{u1, u2, v1, v2}));
  return out;
}

}  // namespace scad::surface::editing
