#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

#include "metadata.hpp"
#include "scad/core/error.hpp"
#include "scad/ops/features/features.hpp"
#include "scad/ops/geometry/geometry.hpp"
#include "scad/semantic/selection.hpp"
#include "scad/semantic/tracked_result.hpp"
#include "scad/std/fastener.hpp"
#include "scad/std/fastener_tables.hpp"
#include "scad/std/validation.hpp"
#include "thread.hpp"

namespace scad {

using namespace stdlib;

namespace {

Solid make_nut_body(const std::string& style, double width, double height, int knurl_count) {
  const Scalar3 origin = scalar3(0.0, 0.0, 0.0);
  if (style == "hex")
    return make_across_flats_prism(6, width, 0.0, height);
  if (style == "square")
    return make_box_rsolid(width, width, height, origin);
  if (style == "round")
    return make_cylinder_rsolid(width / 2.0, height, origin, scalar3(0.0, 0.0, 1.0));

  const double outer_radius = width / 2.0;
  std::vector<Scalar3> points;
  points.reserve(static_cast<std::size_t>(knurl_count) * 2);
  for (int index = 0; index < knurl_count * 2; ++index) {
    const double radius = index % 2 == 0 ? outer_radius : outer_radius * 0.94;
    const double angle = kPi * index / knurl_count;
    points.push_back(scalar3(radius * std::cos(angle), radius * std::sin(angle), 0.0));
  }
  return make_prism(points, height);
}

}  // namespace

Solid make_nut_rsolid(double diameter, double width, double height, const NutOptions& options) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  const double resolved_diameter = positive_finite("diameter", diameter);
  const double resolved_width = positive_finite("width", width);
  const double resolved_height = positive_finite("height", height);
  const std::string nut_style = choice("nut_style", options.nut_style, {"hex", "knurled", "round", "square"});
  const std::string hole_style = choice("hole_style", options.hole_style, {"blind", "through"});
  const std::string thread_detail = choice("thread_detail", options.thread_detail, {"cosmetic", "modeled"});
  const std::string thread_form = choice("thread_form", options.thread_form, {"trapezoidal", "v"});
  const ResolvedPitch resolved_pitch = resolve_thread_pitch(resolved_diameter, options.thread_pitch);
  const double pitch = resolved_pitch.pitch;
  const auto [pitch_diameter, basic_minor_diameter] = metric_thread_dimensions(resolved_diameter, pitch);
  const double default_depth = thread_form == "v" ? (resolved_diameter - basic_minor_diameter) / 2.0 : pitch * 0.5;
  const double depth = options.thread_depth ? positive_finite("thread_depth", *options.thread_depth) : default_depth;
  const double major_radius = resolved_diameter / 2.0;
  if (depth >= major_radius)
    throw ValueError("thread_depth must be smaller than the nut hole radius");
  if (resolved_width / 2.0 <= major_radius + resolved_diameter * 0.05) {
    throw ValueError("width leaves insufficient wall around the nut hole");
  }
  if (options.knurl_count < 8)
    throw ValueError("knurl_count must be an integer of at least 8");

  double hole_depth = resolved_height;
  double hole_start = 0.0;
  if (hole_style == "through") {
    if (options.hole_depth)
      throw ValueError("hole_depth is only valid when hole_style='blind'");
  } else {
    hole_depth = positive_finite("hole_depth", options.hole_depth ? *options.hole_depth : resolved_height * 0.75);
    if (hole_depth >= resolved_height)
      throw ValueError("blind hole_depth must be smaller than height");
    hole_start = resolved_height - hole_depth;
  }
  if (thread_detail == "modeled" && hole_depth <= pitch) {
    throw ValueError("modeled thread depth must be greater than thread_pitch");
  }

  const Solid body = make_nut_body(nut_style, resolved_width, resolved_height, options.knurl_count);
  const double epsilon = std::max(1e-5, resolved_diameter * 1e-4);
  const bool through = hole_style == "through";
  const double cut_start = through ? -epsilon : hole_start;
  const double cut_height = through ? hole_depth + 2.0 * epsilon : hole_depth + epsilon;
  const Solid hole =
      make_cylinder_rsolid(major_radius, cut_height, scalar3(0.0, 0.0, cut_start), scalar3(0.0, 0.0, 1.0));
  CutOptions cut;
  cut.skip_non_intersecting = false;
  Solid nut = cut_rsolid({body, hole}, cut);

  double thread_phase_degrees = 0.0;
  if (thread_detail == "modeled") {
    ThreadCutterSpec spec;
    spec.inner_radius = major_radius - depth;
    spec.outer_radius = major_radius + depth * 0.23;
    spec.pitch = pitch;
    spec.start_z = hole_start;
    spec.length = hole_depth;
    spec.thread_form = thread_form;
    Solid ridge = make_thread_cutter(spec);
    thread_phase_degrees = select_internal_thread_phase(nut, body, ridge);
    ridge = rotate_thread_cutter(ridge, thread_phase_degrees);
    UnionOptions fuse;
    fuse.glue = false;
    nut = union_rsolid({nut, ridge}, fuse);
  }
  nut = Solid(apply_tag(nut, "role.fastener.nut"));
  nut = Solid(apply_tag(nut, "group.fasteners"));
  nut.set_metadata(
      "std.fastener.nut",
      Dict("diameter", resolved_diameter)("width", resolved_width)("height", resolved_height)("nut_style", nut_style)(
          "hole_style", hole_style)("hole_depth", hole_depth)("hole_start", hole_start)("thread_detail", thread_detail)(
          "thread_form", thread_form)("thread_pitch", pitch)("thread_pitch_source", resolved_pitch.source)(
          "thread_depth", depth)("pitch_diameter", pitch_diameter)("basic_minor_diameter", basic_minor_diameter)(
          "modeled_minor_diameter", resolved_diameter - 2.0 * depth)("thread_phase_degrees", thread_phase_degrees)(
          "knurl_count", options.knurl_count)
          .take());
  return nut;
}

}  // namespace scad
