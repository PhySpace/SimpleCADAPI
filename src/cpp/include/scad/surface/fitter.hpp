// The narrow interface behind which the surface operators keep their fitting and
// approximation work.
//
// Everything that turns data (points, curves, constraints) into a free-form NURBS
// surface goes through SurfaceFitter.  The default is built on OpenCASCADE
// (GeomAPI_PointsToBSplineSurface, BRepOffsetAPI_MakeFilling, DLR's occ_gordon); a
// provider with better fitting (SMLib, see docs/research/smlib-usd-brep.md) can be
// installed with set_surface_fitter() without touching an operator.  A provider returns
// geometry, never topology: faces, holes, sewing and tags stay in OpenCASCADE.
//
// Providers must be safe to call from several threads, or lock internally.
#pragma once

#include <memory>
#include <optional>
#include <vector>

#include <Geom_BSplineSurface.hxx>
#include <Geom_Curve.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>

#include "scad/core/vec.hpp"
#include "scad/surface/types.hpp"

namespace scad::surface {

struct GridFit {
  double tolerance = 1e-3;
  int degree_min = 3;
  int degree_max = 8;
  // Weights of the three smoothing terms; nullopt = plain tolerance-driven fit.
  std::optional<std::array<double, 3>> smoothing;
};

// One edge of a filling problem, in the continuity the surface must reach there.
struct FillingBoundary {
  TopoDS_Edge edge;
  TopoDS_Face support;  // null = unsupported (C0 only)
  std::string continuity = "C0";
};

struct FillingProblem {
  std::vector<FillingBoundary> boundaries;
  std::vector<Vec3> points;  // extra points the surface must pass through (global frame)
  SurfaceFillingSettings settings;
};

class SurfaceFitter {
 public:
  virtual ~SurfaceFitter() = default;

  // A B-spline surface through (or within tolerance of) a rectangular point grid.
  // Throws when the fit does not converge.
  virtual Handle(Geom_BSplineSurface) fit_point_grid(const PointGrid& points, const GridFit& options) const = 0;

  // A bounded face spanning the boundaries; the result is exactly one face.
  virtual TopoDS_Face fill(const FillingProblem& problem) const = 0;

  // The Gordon interpolation of a curve network: `profiles` run in u, `guides` in v, and
  // every profile must meet every guide within `tolerance`.
  virtual Handle(Geom_BSplineSurface) gordon(const std::vector<Handle(Geom_Curve)>& profiles,
                                             const std::vector<Handle(Geom_Curve)>& guides,
                                             double tolerance) const = 0;
};

// The provider in use; the OpenCASCADE one unless replaced.
std::shared_ptr<const SurfaceFitter> surface_fitter();
std::shared_ptr<const SurfaceFitter> occt_surface_fitter();
// nullptr restores the OpenCASCADE provider.
void set_surface_fitter(std::shared_ptr<const SurfaceFitter> fitter);

// True when this build can interpolate curve networks (SCAD_WITH_GORDON).
bool gordon_available() noexcept;

}  // namespace scad::surface
