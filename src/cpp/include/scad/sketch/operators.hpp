// The functional sketch API: port of simplecadapi/operators/sketch.py.
//
// Every operator takes a Sketch and returns an updated *copy* (sketches are
// values; the input is never changed), records itself through scad::record_operation,
// and fails with scad::Error carrying the Python operation name and guidance --
// except the constrain_* family, which like the Python code lets plain ValueError
// escape for a bad target.  `targets` accept a SketchRef or an id / "entity.sub" path.
#pragma once

#include <optional>
#include <string>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/sketch/profile.hpp"
#include "scad/sketch/sketch.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

using SketchConstraintId = std::optional<std::string>;

// ---- documents and entities ------------------------------------------------

// `plane`: "XY" | "XZ" | "YZ" or {"origin", "x_axis", "y_axis"}, read in the
// *current* coordinate system (the sketch stores it in world coordinates).
Sketch make_sketch_rsketch(const std::optional<std::string>& name = std::nullopt, const Value& plane = Value("XY"),
                           const std::optional<std::string>& sketch_id = std::nullopt);

Sketch add_point_rsketch(const Sketch& sketch, const std::string& point_id, const Scalar& x, const Scalar& y);
Sketch add_line_rsketch(const Sketch& sketch, const std::string& entity_id, const SketchTarget& start,
                        const SketchTarget& end, bool construction = false);
Sketch add_circle_rsketch(const Sketch& sketch, const std::string& entity_id, const SketchTarget& center,
                          const Scalar& radius, bool construction = false);
Sketch add_ellipse_rsketch(const Sketch& sketch, const std::string& entity_id, const SketchTarget& center,
                           const SketchTarget& major_point, const SketchTarget& minor_point, bool construction = false);
Sketch add_bspline_rsketch(const Sketch& sketch, const std::string& entity_id, const SketchTarget& start,
                           const SketchTarget& end, const std::vector<SketchControlPoint>& control_points,
                           int degree = 3, const std::optional<std::vector<Scalar>>& knots = std::nullopt,
                           const std::optional<std::vector<int>>& multiplicities = std::nullopt,
                           const std::optional<std::vector<Scalar>>& weights = std::nullopt, bool periodic = false,
                           bool construction = false);
Sketch add_arc_rsketch(const Sketch& sketch, const std::string& entity_id, const SketchTarget& start,
                       const SketchTarget& end, const SketchTarget& center, bool construction = false);

SketchRef get_sketch_entity_rsketchref(const Sketch& sketch, const std::string& entity_id);
SketchRef get_sketch_point_rsketchref(const Sketch& sketch, const std::string& point_path);

// ---- constraints -------------------------------------------------------------
// _constrain_rsketch: any constraint kind by name, the targets unchecked against a kind (what graph replay calls).
Sketch constrain_rsketch(const Sketch& sketch, const std::string& kind, const std::vector<SketchTarget>& targets,
                         const std::optional<Scalar>& value = std::nullopt,
                         const SketchConstraintId& constraint_id = std::nullopt, bool driving = true,
                         Value metadata = Value());

Sketch constrain_coincident_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                    const SketchConstraintId& constraint_id = std::nullopt);
// Alias of constrain_coincident_rsketch (records the same constraint kind).
Sketch constrain_connect_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                 const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_point_on_rsketch(const Sketch& sketch, const SketchTarget& point, const SketchTarget& entity,
                                  const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_horizontal_rsketch(const Sketch& sketch, const SketchTarget& line,
                                    const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_vertical_rsketch(const Sketch& sketch, const SketchTarget& line,
                                  const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_points_horizontal_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                           const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_points_vertical_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                         const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_line_distance_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                       const Scalar& value, const SketchConstraintId& constraint_id = std::nullopt,
                                       bool driving = true);
Sketch constrain_normal_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_mirror_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& axis,
                                const SketchTarget& b, const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_midpoint_points_rsketch(const Sketch& sketch, const SketchTarget& mid, const SketchTarget& a,
                                         const SketchTarget& b, const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_parallel_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                  const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_perpendicular_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                       const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_collinear_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                   const SketchConstraintId& constraint_id = std::nullopt);
// `at_a` / `at_b`: "start" | "end" (arc and B-spline endpoint tangency);
// `mode`: "external" | "internal" (circle-circle).  ValueError otherwise.
Sketch constrain_tangent_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                 const std::optional<std::string>& at_a = std::nullopt,
                                 const std::optional<std::string>& at_b = std::nullopt,
                                 const std::string& mode = "external",
                                 const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_concentric_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                    const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_midpoint_rsketch(const Sketch& sketch, const SketchTarget& point, const SketchTarget& line,
                                  const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_symmetric_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                   const SketchTarget& axis, const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_equal_length_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                      const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_equal_radius_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                      const SketchConstraintId& constraint_id = std::nullopt);
Sketch constrain_distance_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                  const Scalar& value, const SketchConstraintId& constraint_id = std::nullopt,
                                  bool driving = true);
Sketch constrain_distance_x_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                    const Scalar& value, const SketchConstraintId& constraint_id = std::nullopt,
                                    bool driving = true);
Sketch constrain_distance_y_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                    const Scalar& value, const SketchConstraintId& constraint_id = std::nullopt,
                                    bool driving = true);
Sketch constrain_length_rsketch(const Sketch& sketch, const SketchTarget& line, const Scalar& value,
                                const SketchConstraintId& constraint_id = std::nullopt, bool driving = true);
Sketch constrain_angle_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b, const Scalar& value,
                               const SketchConstraintId& constraint_id = std::nullopt, bool driving = true);
Sketch constrain_radius_rsketch(const Sketch& sketch, const SketchTarget& circle, const Scalar& value,
                                const SketchConstraintId& constraint_id = std::nullopt, bool driving = true);
Sketch constrain_diameter_rsketch(const Sketch& sketch, const SketchTarget& circle, const Scalar& value,
                                  const SketchConstraintId& constraint_id = std::nullopt, bool driving = true);
Sketch constrain_major_radius_rsketch(const Sketch& sketch, const SketchTarget& ellipse, const Scalar& value,
                                      const SketchConstraintId& constraint_id = std::nullopt, bool driving = true);
Sketch constrain_minor_radius_rsketch(const Sketch& sketch, const SketchTarget& ellipse, const Scalar& value,
                                      const SketchConstraintId& constraint_id = std::nullopt, bool driving = true);
Sketch constrain_fix_rsketch(const Sketch& sketch, const SketchTarget& target,
                             const SketchConstraintId& constraint_id = std::nullopt);

// ---- solving and promotion -----------------------------------------------------

// Solve a copy of the sketch; the input keeps no solve result.  strict=false
// returns conflicting / failed results instead of raising.
SketchSolveResult inspect_sketch_rsketchresult(const Sketch& sketch, const SketchSolveRequest& request = {});

// Promote a profile (closed loop or open chain) to a wire, solving internally.
Wire make_wire_from_sketch_rwire(const Sketch& sketch, const SketchProfileId& profile = 0,
                                 const SketchSolveRequest& request = {});

// Promote an outer profile and optional hole profiles to a face.
Face make_face_from_sketch_rface(const Sketch& sketch, const SketchProfileId& profile = 0,
                                 const std::vector<SketchProfileId>& inner_profiles = {},
                                 const SketchSolveRequest& request = {});

// The legacy container's faces: one promoted face when the sketch has entities,
// else a face per closed wire.
std::vector<Face> sketch_to_faces(const Sketch& sketch);

}  // namespace scad
