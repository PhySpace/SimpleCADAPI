// Gordon interpolation of a curve network: the adapter over DLR's occ_gordon.
#pragma once

#include <vector>

#include <Geom_BSplineSurface.hxx>
#include <Geom_Curve.hxx>
#include <TopoDS_Edge.hxx>

namespace scad::surface::detail {

#ifdef SCAD_WITH_GORDON
inline constexpr bool kGordonAvailable = true;
#else
inline constexpr bool kGordonAvailable = false;
#endif

// The 3D curve of `edge` in global coordinates, trimmed to the edge's range.  A BSpline or
// Bezier edge that spans its whole curve, and a closed periodic one, is passed untrimmed.
Handle(Geom_Curve) network_curve_of(const TopoDS_Edge& edge);

// ocp_gordon.interpolate_curve_network: every curve becomes a non-rational B-spline where
// possible (conics are approximated), then occ_gordon builds the surface.  Throws when this
// build has no Gordon support (SCAD_WITH_GORDON=OFF).
Handle(Geom_BSplineSurface) interpolate_curve_network(const std::vector<Handle(Geom_Curve)>& profiles,
                                                      const std::vector<Handle(Geom_Curve)>& guides,
                                                      double tolerance);

}  // namespace scad::surface::detail
