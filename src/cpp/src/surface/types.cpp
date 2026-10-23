#include "scad/surface/types.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>

#include "scad/core/error.hpp"

namespace scad {

SurfaceBoundary::SurfaceBoundary(Edge edge_, std::string continuity_, std::optional<Face> support_)
    : edge(std::move(edge_)), continuity(std::move(continuity_)), support(std::move(support_)) {
  std::transform(continuity.begin(), continuity.end(), continuity.begin(),
                 [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
  if (continuity != "C0" && continuity != "G1" && continuity != "G2")
    throw ValueError("SurfaceBoundary.continuity must be C0, G1, or G2");
}

Value SurfaceBoundary::as_dict() const {
  Value out = Value::object();
  out.set("continuity", continuity);
  out.set("has_support", support.has_value());
  return out;
}

void SurfaceFillingSettings::validate() const {
  if (degree < 1 || points_per_curve < 2 || iterations < 1)
    throw ValueError("filling degree, points_per_curve, and iterations must be positive");
  if (max_degree < degree || max_segments < 1)
    throw ValueError("max_degree must cover degree and max_segments must be positive");
  const std::pair<const char*, double> tolerances[] = {{"tolerance_2d", tolerance_2d},
                                                       {"tolerance_3d", tolerance_3d},
                                                       {"angular_tolerance", angular_tolerance},
                                                       {"curvature_tolerance", curvature_tolerance}};
  for (const auto& [name, value] : tolerances)
    if (!std::isfinite(value) || value <= 0)
      throw ValueError(std::string(name) + " must be a positive finite value");
}

Value SurfaceFillingSettings::as_dict() const {
  Value out = Value::object();
  out.set("degree", degree);
  out.set("points_per_curve", points_per_curve);
  out.set("iterations", iterations);
  out.set("anisotropic", anisotropic);
  out.set("tolerance_2d", tolerance_2d);
  out.set("tolerance_3d", tolerance_3d);
  out.set("angular_tolerance", angular_tolerance);
  out.set("curvature_tolerance", curvature_tolerance);
  out.set("max_degree", max_degree);
  out.set("max_segments", max_segments);
  return out;
}

}  // namespace scad
