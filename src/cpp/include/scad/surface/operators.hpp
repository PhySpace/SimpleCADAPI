// The surface and shell operators: the surface half of simplecadapi/operators/geometry.py.
//
// Names, arguments, defaults, error operations and recorded parameters follow the Python
// SDK; keyword-only arguments become fields of an options struct (use designated
// initializers: `{.tolerance = 1e-4, .tag_prefix = "skin"}`).  Every operator reports
// failures as scad::Error with the Python operation name and guidance text.
#pragma once

#include <optional>
#include <string>
#include <vector>

#include "scad/surface/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// ---- faces from data -----------------------------------------------------------------

// A trimmed Face carrying a tensor-product Bezier surface.  `control_points` are in the current
// coordinate system; `weights` (positive, same grid shape) make the surface rational.
Face make_bezier_surface_rface(const PointGrid& control_points,
                               const std::optional<WeightGrid>& weights = std::nullopt,
                               const TagPrefix& tag_prefix = std::nullopt);

struct CylindricalSurfaceOptions {
  ScalarVec3 origin{0, 0, 0};
  ScalarVec3 axis{0, 0, 1};
  std::optional<ScalarVec3> x_direction;  // default: the canonical in-plane X for `axis`
  Scalar tolerance = 1e-7;
  TagPrefix tag_prefix;
};

// A finite cylindrical carrier Face over explicit U/V ranges.  radius, V and tolerance are model
// lengths; U is unitless raw radians, increasing, at most one revolution.
Face make_cylindrical_surface_rface(const Scalar& radius, const ScalarRange& u_range, const ScalarRange& v_range,
                                    const CylindricalSurfaceOptions& options = {});

struct FitPointGridOptions {
  double tolerance = 1e-3;
  int degree_min = 3;
  int degree_max = 8;
  std::optional<std::array<double, 3>> smoothing;  // three non-negative smoothing weights
  TagPrefix tag_prefix;
};

// A B-spline Face fitted through a rectangular 3D point grid (current coordinate system).
Face fit_point_grid_rface(const PointGrid& points, const FitPointGridOptions& options = {});

// ---- faces from edges ------------------------------------------------------------------

// A ruled Face spanning two compatible edges.
Face make_ruled_surface_rface(const Edge& edge_a, const Edge& edge_b, const TagPrefix& tag_prefix = std::nullopt);

// A Gordon Face interpolating a network of intersecting profile and guide edges.
Face make_gordon_surface_rface(const std::vector<Edge>& profiles, const std::vector<Edge>& guides,
                               double tolerance = 1e-3, const TagPrefix& tag_prefix = std::nullopt);

struct SurfacePatchOptions {
  std::vector<Vec3> points;  // extra points to pass through (current coordinate system)
  std::optional<SurfaceFillingSettings> settings;
  std::vector<Wire> holes;
  TagPrefix tag_prefix;
};

// A constrained boundary network filled into one Face, optionally with holes.  The filling kernel
// re-fits every boundary edge: patches that must share exact edges and sew into a closed shell
// belong to make_gordon_surface_rface on a shared edge network.
Face make_surface_patch_rface(const std::vector<SurfaceBoundary>& boundaries,
                              const SurfacePatchOptions& options = {});

struct TrimSurfaceOptions {
  std::vector<Wire> holes;
  double tolerance = 1e-7;
  TagPrefix tag_prefix;
};

// Trim a carrier Face to exactly one connected Face bounded by `outer` (and without `holes`).
Face trim_surface_rface(const Face& carrier, const Wire& outer, const TrimSurfaceOptions& options = {});

// ---- shells ------------------------------------------------------------------------------

struct LoftShellTags {
  TagPrefix tag_prefix;
  std::optional<std::string> result_tag;
  std::optional<std::string> start_wire_tag;
  std::optional<std::string> end_wire_tag;
  std::optional<std::string> side_faces_tag;
};

// An open loft Shell through Wire sections (a Vertex is allowed first and last), with named
// endpoint wires and side faces.
Shell loft_rshell(const std::vector<LoftSection>& sections, bool ruled = false, const LoftShellTags& tags = {});

// Sew faces into exactly one connected Shell.
Shell sew_faces_rshell(const std::vector<Face>& faces, double tolerance = 1e-6,
                       const TagPrefix& tag_prefix = std::nullopt);

// One oriented Solid from one valid closed Shell.
Solid make_solid_from_shell_rsolid(const Shell& shell, const TagPrefix& tag_prefix = std::nullopt);

// The unique closed and open free boundary wires of a Shell (closed ones first).
std::vector<Wire> free_boundaries_rwirelist(const Shell& shell, double tolerance = 1e-6);

struct FillHolesOptions {
  std::optional<std::vector<int>> hole_indices;  // indices into free_boundaries_rwirelist; default: all
  double tolerance = 1e-6;
  std::optional<SurfaceFillingSettings> settings;
  TagPrefix tag_prefix;
};

// Fill the selected closed free boundaries of a Shell and return the sewn Shell.
Shell fill_holes_rshell(const Shell& shell, const FillHolesOptions& options = {});

}  // namespace scad
