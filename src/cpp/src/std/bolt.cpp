#include <algorithm>
#include <cmath>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

#include "metadata.hpp"
#include "scad/core/tolerance.hpp"
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
    if (const auto catalog = metric_hex_head_dimensions(diameter))
      return {catalog->width, catalog->height};
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
  if (candidates.size() != 1)
    throw ValueError("could not identify one circular underhead transition edge");
  return candidates.front();
}

Solid make_bolt_head(const std::string& head_style, double width, double height, double shank_radius) {
  const Scalar3 below_head = scalar3(0.0, 0.0, -height);
  const Scalar3 axis = scalar3(0.0, 0.0, 1.0);
  if (head_style == "hex")
    return make_across_flats_prism(6, width, -height, height);
  if (head_style == "square")
    return make_box_rsolid(width, width, height, below_head);
  if (head_style == "cylindrical")
    return make_cylinder_rsolid(width / 2.0, height, below_head, axis);
  if (head_style == "countersunk")
    return make_cone_rsolid(width / 2.0, height, shank_radius, below_head, axis);

  const double radius = width / 2.0;
  const Wire profile = make_polyline_rwire(
      {scalar3(0.0, 0.0, -height), scalar3(radius * 0.42, 0.0, -height), scalar3(radius * 0.82, 0.0, -height * 0.62),
       scalar3(radius, 0.0, -height * 0.22), scalar3(radius, 0.0, 0.0), scalar3(0.0, 0.0, 0.0)},
      /*closed=*/true);
  const Face face = make_face_from_wire_rface(profile, scalar3(0.0, -1.0, 0.0));
  return revolve_rsolid(face, axis, 360.0, scalar3(0.0, 0.0, 0.0));
}

std::vector<Solid> drive_cutters(const std::string& drive_style, double drive_size, double drive_depth,
                                 double head_height) {
  if (drive_style == "none")
    return {};
  const double epsilon = std::max(tol::kCutterOverrunFloor, head_height * tol::kCutterOverrunRelative);
  const Scalar3 cutter_origin = scalar3(0.0, 0.0, -head_height - epsilon);
  const double cutter_height = drive_depth + epsilon;
  const double slot_width = std::max(drive_size * 0.22, epsilon * 10.0);
  if (drive_style == "slot")
    return {make_box_rsolid(drive_size, slot_width, cutter_height, cutter_origin)};
  if (drive_style == "cross") {
    return {make_box_rsolid(drive_size, slot_width, cutter_height, cutter_origin),
            make_box_rsolid(slot_width, drive_size, cutter_height, cutter_origin)};
  }
  const auto points = regular_polygon_points(6, drive_size / 2.0, -head_height - epsilon, kPi / 6.0);
  return {make_prism(points, cutter_height)};
}

}  // namespace

namespace {

// Every resolved and validated bolt parameter; the metadata recorded on the solid is read from here.
struct BoltSpec {
  double diameter = 0.0, length = 0.0;
  std::string head_style, requested_thread_style, thread_style, thread_detail, thread_form, drive_style;
  double head_width = 0.0, head_height = 0.0;
  std::optional<double> head_across_corners;
  double pitch = 0.0;
  std::string pitch_source = "not_applicable";
  double pitch_diameter = 0.0, basic_minor_diameter = 0.0;
  double depth = 0.0, major_radius = 0.0, modeled_minor_diameter = 0.0;
  double thread_length = 0.0, thread_start = 0.0;
  double drive_size = 0.0, drive_depth = 0.0;
  double fillet_radius = 0.0;
  // Set while building: where the modeled thread actually starts, and the phase chosen for it.
  double modeled_thread_start = 0.0, modeled_thread_length = 0.0, thread_phase_degrees = 0.0;
};

// Thread pitch, depth, length and start. 'auto' picks full or partial from the length/diameter ratio.
void resolve_thread(BoltSpec& b, const BoltOptions& options) {
  b.pitch_diameter = b.diameter;
  b.basic_minor_diameter = b.diameter;
  if (!(b.thread_style == "none" && !options.thread_pitch)) {
    const ResolvedPitch resolved = resolve_thread_pitch(b.diameter, options.thread_pitch);
    b.pitch = resolved.pitch;
    b.pitch_source = resolved.source;
    std::tie(b.pitch_diameter, b.basic_minor_diameter) = metric_thread_dimensions(b.diameter, b.pitch);
  }
  const double default_depth =
      b.thread_form == "v" && b.pitch > 0.0 ? (b.diameter - b.basic_minor_diameter) / 2.0 : b.pitch * 0.5;
  b.depth = options.thread_depth ? positive_finite("thread_depth", *options.thread_depth) : default_depth;
  b.major_radius = b.diameter / 2.0;
  if (b.thread_style != "none" && b.depth >= b.major_radius)
    throw ValueError("thread_depth must be smaller than the bolt radius");
  b.modeled_minor_diameter = b.diameter - 2.0 * b.depth;

  if (b.thread_style == "none") {
    b.thread_start = b.length;
  } else if (b.thread_style == "full") {
    if (options.thread_length)
      throw ValueError("thread_length is only valid when thread_style='partial'");
    b.thread_length = b.length;
  } else {
    if (!options.thread_length) {
      b.thread_length = standard_partial_thread_length(b.diameter, b.length);
      if (b.requested_thread_style == "auto" && b.thread_length >= b.length) {
        b.thread_style = "full";
        b.thread_length = b.length;
      }
    } else {
      b.thread_length = positive_finite("thread_length", *options.thread_length);
    }
    if (b.thread_length <= 0.0)
      throw ValueError("partial threads require positive unthreaded shank length");
    if (b.thread_style == "partial" && b.thread_length >= b.length) {
      throw ValueError("partial thread_length must be smaller than length");
    }
    b.thread_start = b.thread_style == "full" ? 0.0 : b.length - b.thread_length;
  }
  if (b.thread_style != "none" && b.thread_detail == "modeled" && b.thread_length <= b.pitch) {
    throw ValueError("modeled thread length must be greater than thread_pitch");
  }
}

// Drive recess size/depth and the under-head fillet radius, each checked against the head size.
void resolve_drive_and_fillet(BoltSpec& b, const BoltOptions& options) {
  if (b.drive_style != "none") {
    b.drive_size = optional_positive("drive_size", options.drive_size, b.head_width * 0.48);
    b.drive_depth = optional_positive("drive_depth", options.drive_depth, b.head_height * 0.28);
    if (b.drive_size >= b.head_width * 0.85)
      throw ValueError("drive_size is too large for head_width");
    if (b.drive_depth >= b.head_height * 0.8)
      throw ValueError("drive_depth is too large for head_height");
  } else if (options.drive_size || options.drive_depth) {
    throw ValueError("drive_size and drive_depth require a non-'none' drive_style");
  }

  const double default_fillet_radius = b.head_style == "countersunk" ? 0.0 : b.diameter * 0.06;
  b.fillet_radius =
      non_negative_finite("underhead_fillet_radius",
                          options.underhead_fillet_radius ? *options.underhead_fillet_radius : default_fillet_radius);
  const double maximum_fillet_radius = std::min(b.major_radius * 0.3, b.head_height * 0.25);
  if (b.fillet_radius > maximum_fillet_radius) {
    throw ValueError("underhead_fillet_radius is too large for the shank and head dimensions");
  }
}

// Validates the options in a fixed order (the order decides which error a bad input reports first).
BoltSpec resolve_bolt_spec(double diameter, double length, const BoltOptions& options) {
  BoltSpec b;
  b.diameter = positive_finite("diameter", diameter);
  b.length = positive_finite("length", length);
  b.head_style = choice("head_style", options.head_style, {"button", "countersunk", "cylindrical", "hex", "square"});
  b.requested_thread_style = choice("thread_style", options.thread_style, {"auto", "full", "none", "partial"});
  b.thread_style = b.requested_thread_style;
  if (b.requested_thread_style == "auto") {
    if (options.thread_length)
      throw ValueError("thread_length requires thread_style='partial'");
    b.thread_style = b.length <= 3.0 * b.diameter ? "full" : "partial";
  }
  b.thread_detail = choice("thread_detail", options.thread_detail, {"cosmetic", "modeled"});
  b.thread_form = choice("thread_form", options.thread_form, {"trapezoidal", "v"});
  b.drive_style = choice("drive_style", options.drive_style, {"cross", "hex_socket", "none", "slot"});

  const HeadSize default_head = default_head_dimensions(b.diameter, b.head_style);
  b.head_width = optional_positive("head_width", options.head_width, default_head.width);
  b.head_height = optional_positive("head_height", options.head_height, default_head.height);
  if (b.head_width <= b.diameter)
    throw ValueError("head_width must be greater than diameter");
  if (b.head_style == "hex")
    b.head_across_corners = b.head_width / std::cos(kPi / 6.0);

  resolve_thread(b, options);
  resolve_drive_and_fillet(b, options);
  return b;
}

// Shank + head (drive recess cut) fused, then the under-head fillet.
Solid build_bolt_body(const BoltSpec& b) {
  // The shank starts epsilon below z=0 so it overruns into the head before the union (tol::kCutterOverrun*).
  const double epsilon = std::max(tol::kCutterOverrunFloor, b.diameter * tol::kCutterOverrunRelative);
  const Solid shank =
      make_cylinder_rsolid(b.major_radius, b.length + epsilon, scalar3(0.0, 0.0, -epsilon), scalar3(0.0, 0.0, 1.0));
  Solid head = make_bolt_head(b.head_style, b.head_width, b.head_height, b.major_radius);
  if (const std::vector<Solid> cutters = drive_cutters(b.drive_style, b.drive_size, b.drive_depth, b.head_height);
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
  if (b.fillet_radius > 0.0)
    bolt = fillet_rsolid(bolt, std::vector<Edge>{underhead_edge(bolt, b.major_radius)}, b.fillet_radius);
  return bolt;
}

// Cuts the modeled helical thread (a full thread starts after the fillet so it does not run into it).
Solid cut_modeled_thread(Solid bolt, BoltSpec& b) {
  b.modeled_thread_start = b.thread_start;
  b.modeled_thread_length = b.thread_length;
  if (b.thread_style == "full") {
    b.modeled_thread_start = std::max(b.pitch, b.fillet_radius);
    b.modeled_thread_length = b.length - b.modeled_thread_start;
  }
  if (b.thread_style == "none" || b.thread_detail != "modeled")
    return bolt;
  ThreadCutterSpec spec;
  spec.inner_radius = b.major_radius - b.depth;
  spec.outer_radius = b.major_radius + b.depth * 0.23;
  spec.pitch = b.pitch;
  spec.start_z = b.modeled_thread_start;
  spec.length = b.modeled_thread_length;
  spec.thread_form = b.thread_form;
  Solid cutter = make_thread_cutter(spec);
  const double inner_radius = b.major_radius - b.depth;
  const double maximum_removed_volume =
      kPi * (b.major_radius * b.major_radius - inner_radius * inner_radius) * b.modeled_thread_length;
  b.thread_phase_degrees = select_external_thread_phase(bolt, cutter, bolt.volume() - maximum_removed_volume);
  cutter = rotate_thread_cutter(cutter, b.thread_phase_degrees);
  CutOptions cut;
  cut.skip_non_intersecting = false;
  return cut_rsolid({bolt, cutter}, cut);
}

void record_bolt_metadata(Solid& bolt, const BoltSpec& b) {
  bolt.set_metadata(
      "std.fastener.bolt",
      Dict("diameter", b.diameter)("length", b.length)("head_style", b.head_style)("head_width", b.head_width)(
          "head_height", b.head_height)("head_across_corners", number_or_null(b.head_across_corners))(
          "drive_style", b.drive_style)("drive_size", b.drive_size)("drive_depth", b.drive_depth)(
          "requested_thread_style", b.requested_thread_style)("thread_style", b.thread_style)(
          "thread_detail", b.thread_detail)("thread_form", b.thread_form)("thread_pitch", b.pitch)(
          "thread_pitch_source", b.pitch_source)("thread_depth", b.depth)("pitch_diameter", b.pitch_diameter)(
          "basic_minor_diameter", b.basic_minor_diameter)("modeled_minor_diameter", b.modeled_minor_diameter)(
          "thread_start", b.thread_start)("thread_length", b.thread_length)(
          "modeled_thread_start", b.modeled_thread_start)("modeled_thread_length", b.modeled_thread_length)(
          "thread_phase_degrees", b.thread_phase_degrees)("underhead_fillet_radius", b.fillet_radius)(
          "recommended_mating_hole_chamfer_min", b.fillet_radius)
          .take());
}

}  // namespace

Solid make_bolt_rsolid(double diameter, double length, const BoltOptions& options) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  BoltSpec spec = resolve_bolt_spec(diameter, length, options);
  Solid bolt = build_bolt_body(spec);
  bolt = cut_modeled_thread(bolt, spec);
  bolt = Solid(apply_tag(bolt, "role.fastener.bolt"));
  bolt = Solid(apply_tag(bolt, "group.fasteners"));
  record_bolt_metadata(bolt, spec);
  return bolt;
}

}  // namespace scad
