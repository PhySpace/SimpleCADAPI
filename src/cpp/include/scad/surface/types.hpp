// Value types of the surface operators: simplecadapi.operators.geometry's
// SurfaceBoundary and SurfaceFillingSettings, and the argument shapes the
// operators share.
#pragma once

#include <array>
#include <optional>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#include "scad/core/tolerance.hpp"
#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// A rectangular grid of 3D points: rows of columns.
using PointGrid = std::vector<std::vector<Vec3>>;
using WeightGrid = std::vector<std::vector<double>>;

using ScalarVec3 = std::array<Scalar, 3>;
using ScalarRange = std::pair<Scalar, Scalar>;

// `tag_prefix=None` in Python.
using TagPrefix = std::optional<std::string>;

// A loft section is a Wire, or a Vertex at the first or last position.
using LoftSection = std::variant<Wire, Vertex>;

// One edge constraint of make_surface_patch_rface.
struct SurfaceBoundary {
  Edge edge;
  std::string continuity;       // "C0" | "G1" | "G2" (upper case)
  std::optional<Face> support;  // the face the surface must be tangent / curvature continuous to

  // ValueError unless `continuity` is C0, G1 or G2 in any letter case.
  explicit SurfaceBoundary(Edge edge_, std::string continuity_ = "C0", std::optional<Face> support_ = std::nullopt);

  Value as_dict() const;  // {"continuity": ..., "has_support": ...}
};

// Explicit OpenCASCADE filling controls; units are model units and radians.
struct SurfaceFillingSettings {
  int degree = 3;
  int points_per_curve = 15;
  int iterations = 2;
  bool anisotropic = false;
  double tolerance_2d = tol::kFillingTolerance2d;
  double tolerance_3d = tol::kFillingTolerance3d;
  double angular_tolerance = 0.01;
  double curvature_tolerance = 0.1;
  int max_degree = 8;
  int max_segments = 9;

  // The checks of SurfaceFillingSettings.__post_init__ (ValueError).
  void validate() const;
  Value as_dict() const;

  bool operator==(const SurfaceFillingSettings&) const = default;
};

}  // namespace scad
