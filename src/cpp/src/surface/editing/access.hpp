// Shared helpers of the curve / surface editing operators: reading the editable B-spline behind an Edge or a Face,
// the user <-> representation frames, and the plain-data views the inspect operators return.  Not installed.
#pragma once

#include <string>
#include <vector>

#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_Curve.hxx>
#include <Geom_Surface.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>

#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/topo/shape.hpp"

namespace scad::surface::editing {

// ---- naming ------------------------------------------------------------------------------------------------------
// "line", "circle", "ellipse", "hyperbola", "parabola", "bezier", "bspline", "offset", "other".
std::string curve_type_name(const Handle(Geom_Curve) & curve);
// "plane", "cylinder", "cone", "sphere", "torus", "bezier", "bspline", "revolution", "extrusion", "offset", "other".
std::string surface_type_name(const Handle(Geom_Surface) & surface);
// B-spline and Bezier geometry is edited; everything else is analytic (or derived) and needs an explicit conversion.
bool is_freeform(const std::string& type_name);

// ---- the geometry behind a shape -----------------------------------------------------------------------------------
// An edge's 3D curve as stored: the curve in its representation frame, that frame (`location`, absolute), the edge's
// parameter range.  ValueError for an edge without a 3D curve (a degenerated edge).
struct CurveRep {
  Handle(Geom_Curve) curve;
  TopLoc_Location location;
  double first = 0.0, last = 0.0;
};
CurveRep curve_rep(const TopoDS_Edge& edge);

struct SurfaceRep {
  Handle(Geom_Surface) surface;
  TopLoc_Location location;
};
SurfaceRep surface_rep(const TopoDS_Face& face);

// A private B-spline copy of a curve / surface with the same parametrisation (trimmed wrappers unwrapped, a Bezier
// converted exactly); null when the geometry is not B-spline or Bezier.
Handle(Geom_BSplineCurve) bspline_copy(const Handle(Geom_Curve) & curve);
Handle(Geom_BSplineSurface) bspline_copy(const Handle(Geom_Surface) & surface);

// The editable B-spline of an edge / face; ValueError naming the explicit conversion for anything else.
struct EditableCurve {
  Handle(Geom_BSplineCurve) curve;  // a private copy: safe to edit
  TopLoc_Location location;
  double first = 0.0, last = 0.0;
};
EditableCurve editable_curve(const Edge& edge);

struct EditableSurface {
  Handle(Geom_BSplineSurface) surface;  // a private copy: safe to edit
  TopLoc_Location location;
};
EditableSurface editable_surface(const Face& face);

// ---- frames ------------------------------------------------------------------------------------------------------
// A position / vector given in the current coordinate system, in a representation frame, and back.
gp_Pnt rep_point(const Vec3& user, const TopLoc_Location& location);
Vec3 user_point(const gp_Pnt& rep, const TopLoc_Location& location);
Vec3 user_vector(const gp_Vec& rep, const TopLoc_Location& location);

// Finite, else ValueError("<label> must contain finite coordinates").
void require_finite(const Vec3& point, const std::string& label);

// ---- plain data --------------------------------------------------------------------------------------------------
Value point_value(const Vec3& point);
// {degree, poles, weights, knots, multiplicities, periodic, rational, closed, domain} of a curve (poles in the user
// frame through `location`).
Value curve_data(const Handle(Geom_BSplineCurve) & curve, const TopLoc_Location& location);
// {u_degree, v_degree, poles, weights, u_knots, v_knots, u_multiplicities, v_multiplicities, u_periodic, v_periodic,
// rational, domain} of a surface.
Value surface_data(const Handle(Geom_BSplineSurface) & surface, const TopLoc_Location& location);

}  // namespace scad::surface::editing
