#include <algorithm>
#include <cmath>
#include <optional>
#include <string>
#include <tuple>
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

double optional_positive(std::string_view name, const std::optional<double>& value, double fallback) {
  return positive_finite(name, value ? *value : fallback);
}

struct HeadSize {
  double width, height;
};

HeadSize default_head_dimensions(double diameter, const std::string& head_style) {
  if (head_style == "hex") {
    if (const auto catalog = metric_hex_head_dimensions(diameter)) return {catalog->width, catalog->height};
  }
  double width_factor = 2.0;
  double height_factor = 0.60;
  if (head_style == "hex") {
    width_factor = 1.6;
    height_factor = 0.65;
  } else if (head_style == "square") {
    width_factor = 1.5;
    height_factor = 0.70;
  } else if (head_style == "cylindrical") {
    width_factor = 1.5;
    height_factor = 1.0;
  } else if (head_style == "button") {
    width_factor = 1.8;
    height_factor = 0.55;
  }
  return {diameter * width_factor, diameter * height_factor};
}

// The circular edge where the shank leaves the head's underside plane.
Edge underhead_edge(const Solid& solid, double shank_radius) {
  const double circumference = 2.0 * kPi * shank_radius;
  std::vector<Edge> candidates;
  for (const Edge& edge : solid.edges()) {
    if (std::fabs(edge.center().z) <= std::max(1e-7, shank_radius * 1e-5) &&
        std::fabs(edge.length() - circumference) <= circumference * 0.05) {
      candidates.push_back(edge);
    }
  }
  if (candidates.size() != 1) throw ValueError("could not identify one circular underhead transition edge");
  return candidates.front();
}

Solid make_bolt_head(const std::string& head_style, double width, double height, double shank_radius) {
  const Scalar3 below_head = scalar3(0.0, 0.0, -height);
  const Scalar3 axis = scalar3(0.0, 0.0, 1.0);
  if (head_style == "hex") return make_across_flats_prism(6, width, -height, height);
  if (head_style == "square") return make_box_rsolid(width, width, height, below_head);
  if (head_style == "cylindrical") return make_cylinder_rsolid(width / 2.0, height, below_head, axis);
  if (head_style == "countersunk") return make_cone_rsolid(width / 2.0, height, shank_radius, below_head, axis);

  const double radius = width / 2.0;
  const Wire profile = make_polyline_rwire({scalar3(0.0, 0.0, -height), scalar3(radius * 0.42, 0.0, -height),
                                            scalar3(radius * 0.82, 0.0, -height * 0.62),
                                            scalar3(radius, 0.0, -height * 0.22), scalar3(radius, 0.0, 0.0),
                                            scalar3(0.0, 0.0, 0.0)},
                                           /*closed=*/true);
  const Face face = make_face_from_wire_rface(profile, scalar3(0.0, -1.0, 0.0));
  return revolve_rsolid(face, axis, 360.0, scalar3(0.0, 0.0, 0.0));
}

std::vector<Solid> drive_cutters(const std::string& drive_style, double drive_size, double drive_depth,
                                 double head_height) {
  if (drive_style == "none") return {};
  const double epsilon = std::max(1e-5, head_height * 1e-4);
  const Scalar3 cutter_origin = scalar3(0.0, 0.0, -head_height - epsilon);
  const double cutter_height = drive_depth + epsilon;
  const double slot_width = std::max(drive_size * 0.22, epsilon * 10.0);
  if (drive_style == "slot") return {make_box_rsolid(drive_size, slot_width, cutter_height, cutter_origin)};
  if (drive_style == "cross") {
    return {make_box_rsolid(drive_size, slot_width, cutter_height, cutter_origin),
            make_box_rsolid(slot_width, drive_size, cutter_height, cutter_origin)};
  }
  const auto points = regular_polygon_points(6, drive_size / 2.0, -head_height - epsilon, kPi / 6.0);
  return {make_prism(points, cutter_height)};
}

}  // namespace

Solid make_bolt_rsolid(double diameter, double length, const BoltOptions& options) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  const double resolved_diameter = positive_finite("diameter", diameter);
  const double resolved_length = positive_finite("length", length);
  const std::string head_style =
      choice("head_style", options.head_style, {"button", "countersunk", "cylindrical", "hex", "square"});
  const std::string requested_thread_style =
      choice("thread_style", options.thread_style, {"auto", "full", "none", "partial"});
  std::string thread_style = requested_thread_style;
  if (requested_thread_style == "auto") {
    if (options.thread_length) throw ValueError("thread_length requires thread_style='partial'");
    thread_style = resolved_length <= 3.0 * resolved_diameter ? "full" : "partial";
  }
  const std::string thread_detail = choice("thread_detail", options.thread_detail, {"cosmetic", "modeled"});
  const std::string thread_form = choice("thread_form", options.thread_form, {"trapezoidal", "v"});
  const std::string drive_style = choice("drive_style", options.drive_style, {"cross", "hex_socket", "none", "slot"});

  const HeadSize default_head = default_head_dimensions(resolved_diameter, head_style);
  const double head_width = optional_positive("head_width", options.head_width, default_head.width);
  const double head_height = optional_positive("head_height", options.head_height, default_head.height);
  if (head_width <= resolved_diameter) throw ValueError("head_width must be greater than diameter");
  const std::optional<double> head_across_corners =
      head_style == "hex" ? std::optional<double>(head_width / std::cos(kPi / 6.0)) : std::nullopt;

  double pitch = 0.0;
  std::string pitch_source = "not_applicable";
  double pitch_diameter = resolved_diameter;
  double basic_minor_diameter = resolved_diameter;
  if (!(thread_style == "none" && !options.thread_pitch)) {
    const ResolvedPitch resolved = resolve_thread_pitch(resolved_diameter, options.thread_pitch);
    pitch = resolved.pitch;
    pitch_source = resolved.source;
    std::tie(pitch_diameter, basic_minor_diameter) = metric_thread_dimensions(resolved_diameter, pitch);
  }
  const double default_depth = thread_form == "v" && pitch > 0.0 ? (resolved_diameter - basic_minor_diameter) / 2.0
                                                                 : pitch * 0.5;
  const double depth = options.thread_depth ? positive_finite("thread_depth", *options.thread_depth) : default_depth;
  const double major_radius = resolved_diameter / 2.0;
  if (thread_style != "none" && depth >= major_radius) throw ValueError("thread_depth must be smaller than the bolt radius");
  const double modeled_minor_diameter = resolved_diameter - 2.0 * depth;

  double thread_length = 0.0;
  double thread_start = 0.0;
  if (thread_style == "none") {
    thread_start = resolved_length;
  } else if (thread_style == "full") {
    if (options.thread_length) throw ValueError("thread_length is only valid when thread_style='partial'");
    thread_length = resolved_length;
  } else {
    if (!options.thread_length) {
      thread_length = standard_partial_thread_length(resolved_diameter, resolved_length);
      if (requested_thread_style == "auto" && thread_length >= resolved_length) {
        thread_style = "full";
        thread_length = resolved_length;
      }
    } else {
      thread_length = positive_finite("thread_length", *options.thread_length);
    }
    if (thread_length <= 0.0) throw ValueError("partial threads require positive unthreaded shank length");
    if (thread_style == "partial" && thread_length >= resolved_length) {
      throw ValueError("partial thread_length must be smaller than length");
    }
    thread_start = thread_style == "full" ? 0.0 : resolved_length - thread_length;
  }
  if (thread_style != "none" && thread_detail == "modeled" && thread_length <= pitch) {
    throw ValueError("modeled thread length must be greater than thread_pitch");
  }

  double drive_size = 0.0;
  double drive_depth = 0.0;
  if (drive_style != "none") {
    drive_size = optional_positive("drive_size", options.drive_size, head_width * 0.48);
    drive_depth = optional_positive("drive_depth", options.drive_depth, head_height * 0.28);
    if (drive_size >= head_width * 0.85) throw ValueError("drive_size is too large for head_width");
    if (drive_depth >= head_height * 0.8) throw ValueError("drive_depth is too large for head_height");
  } else if (options.drive_size || options.drive_depth) {
    throw ValueError("drive_size and drive_depth require a non-'none' drive_style");
  }

  const double default_fillet_radius = head_style == "countersunk" ? 0.0 : resolved_diameter * 0.06;
  const double fillet_radius = non_negative_finite(
      "underhead_fillet_radius", options.underhead_fillet_radius ? *options.underhead_fillet_radius : default_fillet_radius);
  const double maximum_fillet_radius = std::min(major_radius * 0.3, head_height * 0.25);
  if (fillet_radius > maximum_fillet_radius) {
    throw ValueError("underhead_fillet_radius is too large for the shank and head dimensions");
  }

  const double epsilon = std::max(1e-5, resolved_diameter * 1e-4);
  double thread_phase_degrees = 0.0;
  const Solid shank = make_cylinder_rsolid(major_radius, resolved_length + epsilon, scalar3(0.0, 0.0, -epsilon),
                                           scalar3(0.0, 0.0, 1.0));
  Solid head = make_bolt_head(head_style, head_width, head_height, major_radius);
  if (const std::vector<Solid> cutters = drive_cutters(drive_style, drive_size, drive_depth, head_height);
      !cutters.empty()) {
    std::vector<Solid> pieces{head};
    pieces.insert(pieces.end(), cutters.begin(), cutters.end());
    CutOptions cut;
    cut.skip_non_intersecting = false;
    head = cut_rsolid(pieces, cut);
  }
  UnionOptions fuse;
  fuse.glue = false;
  Solid bolt = union_rsolid({head, shank}, fuse);
  if (fillet_radius > 0.0) bolt = fillet_rsolid(bolt, std::vector<Edge>{underhead_edge(bolt, major_radius)}, fillet_radius);

  double modeled_thread_start = thread_start;
  double modeled_thread_length = thread_length;
  if (thread_style == "full") {
    modeled_thread_start = std::max(pitch, fillet_radius);
    modeled_thread_length = resolved_length - modeled_thread_start;
  }
  if (thread_style != "none" && thread_detail == "modeled") {
    ThreadCutterSpec spec;
    spec.inner_radius = major_radius - depth;
    spec.outer_radius = major_radius + depth * 0.23;
    spec.pitch = pitch;
    spec.start_z = modeled_thread_start;
    spec.length = modeled_thread_length;
    spec.thread_form = thread_form;
    Solid cutter = make_thread_cutter(spec);
    const double inner_radius = major_radius - depth;
    const double maximum_removed_volume = kPi * (major_radius * major_radius - inner_radius * inner_radius) * modeled_thread_length;
    thread_phase_degrees =
        select_external_thread_phase(bolt, cutter, bolt.volume() - maximum_removed_volume);
    cutter = rotate_thread_cutter(cutter, thread_phase_degrees);
    CutOptions cut;
    cut.skip_non_intersecting = false;
    bolt = cut_rsolid({bolt, cutter}, cut);
  }
  bolt = Solid(apply_tag(bolt, "role.fastener.bolt"));
  bolt = Solid(apply_tag(bolt, "group.fasteners"));
  bolt.set_metadata(
      "std.fastener.bolt",
      Dict("diameter", resolved_diameter)("length", resolved_length)("head_style", head_style)("head_width", head_width)(
          "head_height", head_height)("head_across_corners", number_or_null(head_across_corners))(
          "drive_style", drive_style)("drive_size", drive_size)("drive_depth", drive_depth)(
          "requested_thread_style", requested_thread_style)("thread_style", thread_style)(
          "thread_detail", thread_detail)("thread_form", thread_form)("thread_pitch", pitch)(
          "thread_pitch_source", pitch_source)("thread_depth", depth)("pitch_diameter", pitch_diameter)(
          "basic_minor_diameter", basic_minor_diameter)("modeled_minor_diameter", modeled_minor_diameter)(
          "thread_start", thread_start)("thread_length", thread_length)("modeled_thread_start", modeled_thread_start)(
          "modeled_thread_length", modeled_thread_length)("thread_phase_degrees", thread_phase_degrees)(
          "underhead_fillet_radius", fillet_radius)("recommended_mating_hole_chamfer_min", fillet_radius)
          .take());
  return bolt;
}

}  // namespace scad
