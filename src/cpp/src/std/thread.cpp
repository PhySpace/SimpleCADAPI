#include "thread.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <exception>
#include <optional>

#include "scad/core/error.hpp"
#include "scad/core/vec.hpp"
#include "scad/ops/features/features.hpp"
#include "scad/ops/geometry/geometry.hpp"
#include "scad/topo/recorder.hpp"

namespace scad::stdlib {

namespace {

constexpr std::array<double, 16> kPhaseCandidates{0.0,   15.0,  30.0,  45.0,  60.0,  90.0,  120.0, 135.0,
                                                  150.0, 165.0, 180.0, 210.0, 240.0, 270.0, 300.0, 330.0};

std::vector<Scalar3> thread_profile_points(const ThreadCutterSpec& spec, double z) {
  if (spec.thread_form == "v") {
    const double flank_run = (spec.outer_radius - spec.inner_radius) / std::sqrt(3.0);
    const double crest_flat = spec.pitch / 8.0;
    const double root_flat = spec.pitch - crest_flat - 2.0 * flank_run;
    if (root_flat <= 0.0) throw ValueError("thread_depth is too large for a truncated 60-degree V profile");
    return {scalar3(spec.outer_radius, 0.0, z + crest_flat / 2.0),
            scalar3(spec.inner_radius, 0.0, z + crest_flat / 2.0 + flank_run),
            scalar3(spec.inner_radius, 0.0, z + crest_flat / 2.0 + flank_run + root_flat),
            scalar3(spec.outer_radius, 0.0, z + spec.pitch - crest_flat / 2.0)};
  }
  return {scalar3(spec.outer_radius, 0.0, z), scalar3(spec.inner_radius, 0.0, z + spec.pitch * 0.35),
          scalar3(spec.inner_radius, 0.0, z + spec.pitch * 0.65), scalar3(spec.outer_radius, 0.0, z + spec.pitch)};
}

}  // namespace

std::vector<Scalar3> regular_polygon_points(int sides, double circumradius, double z, double phase) {
  std::vector<Scalar3> points;
  points.reserve(static_cast<std::size_t>(sides));
  for (int index = 0; index < sides; ++index) {
    const double angle = phase + 2.0 * kPi * index / sides;
    points.push_back(scalar3(circumradius * std::cos(angle), circumradius * std::sin(angle), z));
  }
  return points;
}

Solid make_prism(const std::vector<Scalar3>& points, double height) {
  const Wire wire = make_polyline_rwire(points, /*closed=*/true);
  const Face face = make_face_from_wire_rface(wire, scalar3(0.0, 0.0, 1.0));
  return extrude_rsolid(face, scalar3(0.0, 0.0, 1.0), height);
}

Solid make_across_flats_prism(int sides, double width, double z, double height) {
  const double radius = width / (2.0 * std::cos(kPi / sides));
  return make_prism(regular_polygon_points(sides, radius, z, kPi / sides), height);
}

Solid make_thread_cutter(const ThreadCutterSpec& spec) {
  const double overrun_start = spec.start_z - spec.pitch;
  const Wire profile = make_polyline_rwire(thread_profile_points(spec, overrun_start), /*closed=*/true);
  const Face profile_face = make_face_from_wire_rface(profile, scalar3(0.0, 1.0, 0.0));
  const Wire helix = make_helix_rwire(spec.pitch, spec.length + 2.0 * spec.pitch, spec.outer_radius,
                                      scalar3(0.0, 0.0, overrun_start), scalar3(0.0, 0.0, 1.0));
  const Solid swept = sweep_rsolid(profile_face, helix, /*is_frenet=*/true);
  const Solid clip = make_cylinder_rsolid(spec.outer_radius + std::max(1e-6, spec.pitch * 0.01), spec.length,
                                          scalar3(0.0, 0.0, spec.start_z), scalar3(0.0, 0.0, 1.0));
  return intersect_rsolid({swept, clip});
}

Solid rotate_thread_cutter(const Solid& cutter, double angle_degrees) {
  if (angle_degrees == 0.0) return cutter;
  return Solid(rotate_shape(cutter, angle_degrees, scalar3(0.0, 0.0, 1.0), scalar3(0.0, 0.0, 0.0)));
}

double select_external_thread_phase(const Solid& shank, const Solid& cutter, double minimum_volume) {
  const double maximum_volume = shank.volume();
  const double volume_tolerance = std::max(1e-8, maximum_volume * 1e-8);
  const RecorderSuspend quiet;
  CutOptions cut;
  cut.skip_non_intersecting = false;
  for (const double angle : kPhaseCandidates) {
    const Solid candidate = rotate_thread_cutter(cutter, angle);
    std::optional<Solid> result;
    try {
      result = cut_rsolid({shank, candidate}, cut);
    } catch (const std::exception&) {
      continue;
    }
    const double volume = result->volume();
    if (minimum_volume * 0.98 < volume && volume < maximum_volume - volume_tolerance) return angle;
  }
  throw ValueError("modeled external thread is unstable for these dimensions");
}

double select_internal_thread_phase(const Solid& opened_nut, const Solid& body, const Solid& ridge) {
  const double minimum_volume = opened_nut.volume();
  const double maximum_volume = body.volume();
  const double volume_tolerance = std::max(1e-8, maximum_volume * 1e-8);
  const RecorderSuspend quiet;
  UnionOptions fuse;
  fuse.glue = false;
  for (const double angle : kPhaseCandidates) {
    const Solid candidate = rotate_thread_cutter(ridge, angle);
    std::optional<Solid> result;
    try {
      result = union_rsolid({opened_nut, candidate}, fuse);
    } catch (const std::exception&) {
      continue;
    }
    const double volume = result->volume();
    if (minimum_volume + volume_tolerance < volume && volume < maximum_volume - volume_tolerance) return angle;
  }
  throw ValueError("modeled internal thread is unstable for these dimensions");
}

}  // namespace scad::stdlib
