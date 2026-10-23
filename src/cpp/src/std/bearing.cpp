#include "scad/std/bearing.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>

#include "bearing_rings.hpp"
#include "metadata.hpp"
#include "scad/core/error.hpp"
#include "scad/ops/features/features.hpp"
#include "scad/ops/geometry/geometry.hpp"
#include "scad/product/operators.hpp"
#include "scad/semantic/selection.hpp"
#include "scad/semantic/tracked_result.hpp"
#include "scad/std/validation.hpp"

namespace scad {

using namespace stdlib;
namespace sp = scad::product;

namespace {

int infer_ball_count(double ball_pitch_radius, double ball_diameter) {
  const double circumference = 2.0 * kPi * ball_pitch_radius;
  // Room for a cage between neighbours instead of tangent spheres around the pitch circle.
  return std::max(3, static_cast<int>(std::floor(circumference / (1.5 * ball_diameter))));
}

int validate_ball_count(const std::optional<int>& ball_count, double ball_pitch_radius, double ball_diameter) {
  const int resolved = ball_count ? *ball_count : infer_ball_count(ball_pitch_radius, ball_diameter);
  if (resolved < 3) throw ValueError("ball_count must be at least 3");
  const double chord_spacing = 2.0 * ball_pitch_radius * std::sin(kPi / resolved);
  if (chord_spacing <= ball_diameter) {
    throw ValueError("ball_count is too high for ball_diameter on the bearing pitch circle");
  }
  return resolved;
}

// The face looking along +Z whose centre is nearest `target_z` (the larger one among equals):
// the datum the bearing's axis connector sits on.
Face axis_face(const Solid& solid, double target_z) {
  std::optional<Face> best;
  double best_distance = 0.0;
  double best_area = 0.0;
  for (const Face& face : solid.faces()) {
    if (face.normal_at().z < 0.7) continue;
    const double distance = std::fabs(face.center().z - target_z);
    const double area = face.area();
    if (!best || distance < best_distance || (distance == best_distance && area > best_area)) {
      best = face;
      best_distance = distance;
      best_area = area;
    }
  }
  if (!best) throw ValueError("no +Z bearing axis face found");
  return *best;
}

sp::PartPtr part_with_axis_connector(const std::string& part_id, const Solid& body, const std::string& name,
                                     double target_z) {
  const sp::PartPtr part = sp::make_part_rpart(part_id, body, name);
  return sp::add_connector_rpart(*part, sp::make_face_connector_rconnector("axis", axis_face(body, target_z)));
}

sp::Placement ball_placement(double ball_pitch_radius, double angle_degrees) {
  const double angle = radians(angle_degrees);
  const double cos_a = std::cos(angle);
  const double sin_a = std::sin(angle);
  return sp::make_placement_rplacement(scalar3(ball_pitch_radius * cos_a, ball_pitch_radius * sin_a, 0.0),
                                       scalar3(cos_a, sin_a, 0.0), scalar3(-sin_a, cos_a, 0.0));
}

// "ball_07": the index zero-padded to at least two digits, wider when there are more than 100 balls.
std::string ball_component_id(int index, int digits) {
  std::ostringstream out;
  out << "ball_" << std::setw(digits) << std::setfill('0') << index;
  return out.str();
}

sp::PartPtr with_material(const sp::PartPtr& part, const std::optional<sp::Material>& material) {
  return material ? sp::assign_material_rpart(*part, *material) : part;
}

}  // namespace

sp::AssemblyPtr make_ball_bearing_rassembly(double bore_diameter, double outer_diameter, double bearing_width,
                                            double ball_diameter, const BallBearingOptions& options) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  const double bore_diameter_value = validate_positive("bore_diameter", bore_diameter);
  const double outer_diameter_value = validate_positive("outer_diameter", outer_diameter);
  const double bearing_width_value = validate_positive("bearing_width", bearing_width);
  const double ball_diameter_value = validate_positive("ball_diameter", ball_diameter);
  const double raceway_clearance = validate_non_negative("raceway_clearance", options.raceway_clearance);
  const double edge_chamfer = validate_non_negative("edge_chamfer", options.edge_chamfer);
  if (outer_diameter_value <= bore_diameter_value) throw ValueError("outer_diameter must be greater than bore_diameter");

  const double bore_radius = bore_diameter_value / 2.0;
  const double outer_radius = outer_diameter_value / 2.0;
  const double ball_radius = ball_diameter_value / 2.0;
  const double ball_pitch_radius = (bore_radius + outer_radius) / 2.0;
  const double groove_radius = ball_radius + raceway_clearance;
  const double inner_groove_root_radius = ball_pitch_radius - groove_radius;
  const double outer_groove_root_radius = ball_pitch_radius + groove_radius;
  const double inner_wall_thickness = inner_groove_root_radius - bore_radius;
  const double outer_wall_thickness = outer_radius - outer_groove_root_radius;
  const double axial_clearance = bearing_width_value / 2.0 - groove_radius;
  if (inner_wall_thickness <= 0.0 || outer_wall_thickness <= 0.0) {
    throw ValueError("ball_diameter plus raceway_clearance leaves no radial wall thickness");
  }
  if (axial_clearance <= 0.0) {
    throw ValueError("bearing_width must be greater than ball_diameter plus raceway_clearance");
  }
  const double smallest_feature = std::min({inner_wall_thickness, outer_wall_thickness, axial_clearance});
  if (edge_chamfer >= smallest_feature) throw ValueError("edge_chamfer must be smaller than the thinnest bearing feature");
  const int ball_count = validate_ball_count(options.ball_count, ball_pitch_radius, ball_diameter_value);

  const Solid outer_ring =
      make_race_ring_solid(ball_pitch_radius + ball_radius * 0.75, outer_radius, ball_pitch_radius, groove_radius,
                           bearing_width_value, edge_chamfer, RingRole::Outer);
  const Solid inner_ring =
      make_race_ring_solid(bore_radius, ball_pitch_radius - ball_radius * 0.75, ball_pitch_radius, groove_radius,
                           bearing_width_value, edge_chamfer, RingRole::Inner);
  Solid ball = make_sphere_rsolid(ball_radius, scalar3(0.0, 0.0, 0.0));
  const bool fuse = options.fuse_rolling_elements;
  if (fuse) {
    if (!std::isfinite(options.rolling_element_fuse_overlap) || options.rolling_element_fuse_overlap <= 0.0) {
      throw ValueError("rolling_element_fuse_overlap must be finite and positive");
    }
    if (options.rolling_element_fuse_overlap >= ball_radius) {
      throw ValueError("rolling_element_fuse_overlap must be smaller than ball radius");
    }
  }
  ball = Solid(apply_tag(ball, "role.rolling_element"));
  ball = Solid(apply_tag(ball, "group.ball_bearing"));
  ball.set_metadata("std.bearing.ball", Dict("diameter", ball_diameter_value)("pitch_radius", ball_pitch_radius).take());

  Solid fused_rolling_ring = outer_ring;
  if (fuse) {
    // The balls sit slightly inside the outer race so the union has a positive-volume intersection
    // instead of a tangent-only contact.
    const double fuse_radius = ball_pitch_radius + ball_radius * 0.75 + options.rolling_element_fuse_overlap;
    std::vector<Solid> pieces{outer_ring};
    for (int index = 0; index < ball_count; ++index) {
      const double angle = 2.0 * kPi * index / ball_count;
      pieces.push_back(make_sphere_rsolid(ball_radius, scalar3(fuse_radius * std::cos(angle), fuse_radius * std::sin(angle), 0.0)));
    }
    UnionOptions fuse_options;
    fuse_options.glue = false;
    fuse_options.tracking_policy = "graph";
    fused_rolling_ring = union_rsolid(pieces, fuse_options);
    fused_rolling_ring = Solid(apply_tag(fused_rolling_ring, "role.rolling_elements_fused_into_outer_ring"));
  }

  const std::string& assembly_id = options.assembly_id;
  const sp::PartPtr outer_part = with_material(
      part_with_axis_connector(assembly_id + "_outer_ring", fused_rolling_ring, "Outer bearing ring", bearing_width_value / 2.0),
      options.material);
  const sp::PartPtr inner_part = with_material(
      part_with_axis_connector(assembly_id + "_inner_ring", inner_ring, "Inner bearing ring", bearing_width_value / 2.0),
      options.material);
  const sp::PartPtr ball_part = with_material(sp::make_part_rpart(assembly_id + "_ball", ball, "Bearing ball"), options.material);

  sp::AssemblyPtr assembly = sp::make_assembly_rassembly(assembly_id, "Ball bearing");
  assembly = sp::add_component_rassembly(*assembly, outer_part, "outer_ring", sp::identity_placement_rplacement());
  assembly = sp::add_component_rassembly(*assembly, inner_part, "inner_ring", sp::identity_placement_rplacement());

  Value ball_component_ids = Value::array();
  Value ball_angles = Value::object();
  if (!fuse) {
    const int digits = std::max<int>(2, static_cast<int>(std::to_string(ball_count - 1).size()));
    for (int index = 0; index < ball_count; ++index) {
      const std::string component_id = ball_component_id(index, digits);
      const double angle_degrees = 360.0 * index / ball_count;
      ball_component_ids.push_back(component_id);
      ball_angles.set(component_id, angle_degrees);
      assembly = sp::add_component_rassembly(*assembly, ball_part, component_id, ball_placement(ball_pitch_radius, angle_degrees));
    }
  }

  assembly = sp::add_revolute_constraint_rassembly(
      *assembly, "inner_outer_revolute", sp::make_connector_ref_rconnectorref("outer_ring", "axis"),
      sp::make_connector_ref_rconnectorref("inner_ring", "axis"),
      options.drive_angle_degrees ? std::optional<Scalar>(Scalar(*options.drive_angle_degrees)) : std::nullopt, {},
      "Inner ring spins in outer ring");
  assembly = sp::set_public_connector_rassembly(*assembly, "outer_axis", "outer_ring", "axis", "Outer ring housing axis");
  assembly = sp::set_public_connector_rassembly(*assembly, "inner_axis", "inner_ring", "axis", "Inner ring shaft axis");

  assembly->set_metadata(
      "std.bearing.ball_bearing",
      Dict("bore_diameter", bore_diameter_value)("outer_diameter", outer_diameter_value)(
          "bearing_width", bearing_width_value)("ball_diameter", ball_diameter_value)("ball_count", ball_count)(
          "raceway_clearance", raceway_clearance)("edge_chamfer", edge_chamfer)("ball_pitch_radius", ball_pitch_radius)(
          "groove_radius", groove_radius)("inner_groove_root_radius", inner_groove_root_radius)(
          "outer_groove_root_radius", outer_groove_root_radius)("inner_wall_thickness", inner_wall_thickness)(
          "outer_wall_thickness", outer_wall_thickness)("axial_clearance", axial_clearance)(
          "outer_component_id", "outer_ring")("inner_component_id", "inner_ring")(
          "ball_component_ids", std::move(ball_component_ids))("ball_angles_degrees", std::move(ball_angles))(
          "rolling_elements_fused", fuse)("rolling_element_fuse_overlap",
                                          fuse ? Value(options.rolling_element_fuse_overlap) : Value())(
          "rolling_element_fuse_mode", fuse ? "outer_ring_union" : "components")("axis_connector_id", "axis")(
          "outer_axis_connector_id", "outer_axis")("inner_axis_connector_id", "inner_axis")(
          "revolute_constraint_id", "inner_outer_revolute")
          .take());
  return assembly;
}

}  // namespace scad
