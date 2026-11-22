// The default SurfaceFitter (OpenCASCADE) and the provider registry.
#include "scad/surface/fitter.hpp"

#include <algorithm>
#include <mutex>

#include <BRepOffsetAPI_MakeFilling.hxx>
#include <GeomAPI_PointsToBSplineSurface.hxx>
#include <GeomAbs_Shape.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TopoDS.hxx>

#include <vector>

// The patched kernel (src/cpp/patches/occt) installs the graph patch as a separate entry point.
#if __has_include(<BRepOffsetAPI_GraphPatch.hxx>)
#include <BRepOffsetAPI_GraphPatch.hxx>
#define SCAD_KERNEL_GRAPH_PATCH 1
#else
#define SCAD_KERNEL_GRAPH_PATCH 0
#endif

#include "gordon.hpp"
#include "internal.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/kernel/membership.hpp"
#include "scad/kernel/topology.hpp"

namespace scad::surface {

namespace {

GeomAbs_Shape order_of(const std::string& continuity) {
  if (continuity == "C0")
    return GeomAbs_C0;
  if (continuity == "G1")
    return GeomAbs_G1;
  if (continuity == "G2")
    return GeomAbs_G2;
  throw ValueError("unknown filling continuity: " + continuity);
}

class OcctSurfaceFitter final : public SurfaceFitter {
 public:
  Handle(Geom_BSplineSurface) fit_point_grid(const PointGrid& points, const GridFit& options) const override {
    const int rows = static_cast<int>(points.size());
    const int columns = static_cast<int>(points.front().size());
    TColgp_Array2OfPnt poles(1, rows, 1, columns);
    for (int row = 0; row < rows; ++row)
      for (int column = 0; column < columns; ++column)
        poles.SetValue(row + 1, column + 1,
                       kernel::to_pnt(points[static_cast<std::size_t>(row)][static_cast<std::size_t>(column)]));

    GeomAPI_PointsToBSplineSurface builder;
    if (options.smoothing) {
      const auto& w = *options.smoothing;
      builder.Init(poles, w[0], w[1], w[2], options.degree_max, GeomAbs_C2, options.tolerance);
    } else {
      builder.Init(poles, options.degree_min, options.degree_max, GeomAbs_C2, options.tolerance);
    }
    if (!builder.IsDone())
      throw ValueError("OCP B-spline point-grid fitting did not converge");
    return builder.Surface();
  }

  // occt_guard: the caller fill_face is only called from operator_scope bodies (faces_from_edges.cpp, shell_ops.cpp),
  // which are guarded.
  TopoDS_Face fill(const FillingProblem& problem) const override {
    if (problem.graph_patch)
      return graph_patch(problem);
    const SurfaceFillingSettings& s = problem.settings;
    BRepOffsetAPI_MakeFilling builder(s.degree, s.points_per_curve, s.iterations, s.anisotropic, s.tolerance_2d,
                                      s.tolerance_3d, s.angular_tolerance, s.curvature_tolerance, s.max_degree,
                                      s.max_segments);
    for (const FillingBoundary& boundary : problem.boundaries) {
      const GeomAbs_Shape order = order_of(boundary.continuity);
      if (boundary.support.IsNull())
        builder.Add(boundary.edge, order);
      else
        builder.Add(boundary.edge, boundary.support, order);
    }
    for (const Vec3& point : problem.points)
      builder.Add(kernel::to_pnt(point));
    builder.Build();
    if (!builder.IsDone())
      throw ValueError("OCP constrained surface filling did not converge");
    return detail::single_face(builder.Shape(), "filling");
  }

  // The ordered loop as BRepOffsetAPI_GraphPatch takes it: each edge from its support face, with
  // its continuity as the numeric order 0/1/2 (GeomAbs_G2 is not the integer 2).
  static TopoDS_Face graph_patch(const FillingProblem& problem) {
#if SCAD_KERNEL_GRAPH_PATCH
    const std::size_t count = problem.boundaries.size();
    if (count < 3 || count > 64)
      throw ValueError("strategy_graph_patch takes one ordered loop of 3 to 64 boundaries, got " +
                       std::to_string(count));
    if (!problem.points.empty())
      throw ValueError("strategy_graph_patch takes no interior points");
    std::vector<TopoDS_Edge> edges;
    std::vector<TopoDS_Face> supports;
    std::vector<int> orders;
    for (std::size_t i = 0; i < count; ++i) {
      const FillingBoundary& b = problem.boundaries[i];
      if (b.support.IsNull())
        throw ValueError("strategy_graph_patch needs a support face on every boundary (boundary " + std::to_string(i) +
                         " has none)");
      if (!kernel::SubShapeIndex(b.support).contains(b.edge))
        throw ValueError(
            "strategy_graph_patch needs each boundary edge to be an edge of its support face "
            "(boundary " +
            std::to_string(i) + ")");
      edges.push_back(b.edge);
      supports.push_back(b.support);
      orders.push_back(b.continuity == "G2" ? 2 : b.continuity == "G1" ? 1 : 0);
    }
    TopoDS_Face face;
    if (!BRepOffsetAPI_GraphPatch::TryBuild(static_cast<int>(count), edges.data(), supports.data(), orders.data(),
                                            face))
      throw ValueError(
          "the graph patch was refused: the loop is not ordered and closed, cannot be represented "
          "over one plane, or the fitted patch failed its boundary or topology checks");
    return face;
#else
    (void)problem;
    throw ValueError(
        "strategy_graph_patch needs an OpenCASCADE kernel built with the SimpleCADAPI patch set "
        "fillet-robustness-4 (src/cpp/patches/occt); this build links one without it");
#endif
  }

  Handle(Geom_BSplineSurface) gordon(const std::vector<Handle(Geom_Curve)>& profiles,
                                     const std::vector<Handle(Geom_Curve)>& guides, double tolerance) const override {
    return detail::interpolate_curve_network(profiles, guides, tolerance);
  }
};

struct Registry {
  std::mutex mutex;
  std::shared_ptr<const SurfaceFitter> installed;
  const std::shared_ptr<const SurfaceFitter> occt = std::make_shared<OcctSurfaceFitter>();
};

Registry& registry() {
  static Registry instance;
  return instance;
}

}  // namespace

std::shared_ptr<const SurfaceFitter> occt_surface_fitter() {
  return registry().occt;
}

bool kernel_has_graph_patch() {
  return SCAD_KERNEL_GRAPH_PATCH != 0;
}

std::shared_ptr<const SurfaceFitter> surface_fitter() {
  Registry& r = registry();
  const std::lock_guard<std::mutex> lock(r.mutex);
  return r.installed ? r.installed : r.occt;
}

void set_surface_fitter(std::shared_ptr<const SurfaceFitter> fitter) {
  Registry& r = registry();
  const std::lock_guard<std::mutex> lock(r.mutex);
  r.installed = std::move(fitter);
}

bool gordon_available() noexcept {
  return detail::kGordonAvailable;
}

}  // namespace scad::surface
