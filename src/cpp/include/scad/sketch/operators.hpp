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
#include "scad/core/coordinate_system.hpp"
#include "scad/core/value.hpp"
#include "scad/sketch/profile.hpp"
#include "scad/sketch/sketch.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

using SketchConstraintId = std::optional<std::string>;

// ---- documents and entities ------------------------------------------------

// `plane`: "XY" | "XZ" | "YZ" or {"origin", "x_axis", "y_axis"}, read in the
// *current* coordinate system (the sketch stores it in world coordinates).  A mapping that also says
// "workplane": true is a world frame already (what a sketch on a workplane records) and is not transformed.
Sketch make_sketch_rsketch(const std::optional<std::string>& name = std::nullopt, const Value& plane = Value("XY"),
                           const std::optional<std::string>& sketch_id = std::nullopt);
// On a workplane: its frame, in world coordinates whatever the current system.  The workplane's node (when it
// was recorded) is an input of the sketch's, and `plane` is recorded as {"workplane": true, origin, x_axis,
// y_axis}, so a replay takes the frame from the replayed workplane.
Sketch make_sketch_rsketch(const std::optional<std::string>& name, const Workplane& plane,
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

// ---- editing: trim, extend and the report of what an edit did --------------------

// A position in the sketch plane: coordinates, or a point of the sketch (it stands for its solved position).
class SketchPosition {
 public:
  SketchPosition() = default;  // only so binding layers can default-construct a slot
  SketchPosition(double x, double y) : xy_(x, y) {}
  SketchPosition(SketchPoint2 xy) : xy_(xy) {}                                   // NOLINT(google-explicit-constructor)
  SketchPosition(SketchTarget point) : point_(std::move(point)) {}               // NOLINT(google-explicit-constructor)
  SketchPosition(std::string point) : point_(SketchTarget(std::move(point))) {}  // NOLINT
  SketchPosition(const char* point) : point_(SketchTarget(point)) {}             // NOLINT

  bool is_point() const noexcept { return point_.has_value(); }
  const SketchTarget& point() const { return *point_; }
  const SketchPoint2& xy() const noexcept { return xy_; }

 private:
  SketchPoint2 xy_{0.0, 0.0};
  std::optional<SketchTarget> point_;
};

// Remove the part of a line / circle / arc `entity` that contains `at`, between the nearest cuts: the places where
// another entity crosses it (`against` limits which ones; default every entity that is not construction), or an end
// of `entity`.  The sketch is solved first and the cuts are made on the solved geometry.  Lines and arcs keep the
// pieces on either side; a circle keeps the arc left over (it needs two cuts); an entity nothing crosses is removed
// whole.  A cut point is tied to the entity that cut it with a point_on constraint, a line piece inherits the
// horizontal / vertical constraint of its line, constraints on `<entity>.start|end|center` stay on the point, and
// constraints that name the removed entity are removed.  New ids: p<n> points, l<n> lines, a<n> arcs (lowest free n,
// never an id the sketch had before), c_<kind>_<n> constraints.
Sketch trim_rsketch(const Sketch& sketch, const SketchTarget& entity, const SketchPosition& at,
                    const std::optional<std::vector<SketchTarget>>& against = std::nullopt);

// Lengthen the line `entity` at its "start" or "end" until it meets `to` (default: the nearest entity ahead): the end
// point moves onto it and is tied to it with a point_on constraint.  Refused when the end point belongs to another
// entity.  The length dimension of the line, and any dimension or fix on the moved point, no longer hold and are
// dropped.
Sketch extend_rsketch(const Sketch& sketch, const SketchTarget& entity, const std::string& end,
                      const std::optional<SketchTarget>& to = std::nullopt);

// A B-spline in anchor form -- cubic, inner knots of multiplicity 3, every control point a sketch point -- is a chain
// of Bezier spans: control points [A0, out0, in1, A1, out1, in2, A2, ...], anchors on the curve with an in- and an
// out-handle each (a pen tool's curve).  These three edit that structure on the solved geometry.
//
// Insert an anchor at the curve point nearest `at` without changing the curve (de Casteljau split of that span): the
// span's two handles get shorter (they keep their ids; a dimension or fix on them is dropped) and the new anchor and
// its two handles are new points p<n>.  Refused at an existing anchor and for a B-spline that is not in anchor form.
Sketch insert_spline_anchor_rsketch(const Sketch& sketch, const SketchTarget& spline, const SketchPosition& at);

// Remove the inner anchor `anchor` (a point id) and its two handles: the spans on either side become one, whose outer
// handles keep their ids and directions and get the lengths that fit the old curve best (a handle a constraint or
// another entity holds keeps its place).  The removed points go unless another entity uses them, and constraints on the
// removed points go with them.  An end anchor cannot be removed.
Sketch remove_spline_anchor_rsketch(const Sketch& sketch, const SketchTarget& spline, const SketchTarget& anchor);

// Write an open B-spline in anchor form: exactly (same curve) for degree <= 3 without weights, else approximated
// within 1e-4.  The end points keep their ids, inner control points that do not move keep theirs, the others are new
// points p<n>; control points no entity uses any more go, with their constraints.  A spline already in anchor form is
// left as it is.
Sketch convert_spline_to_anchors_rsketch(const Sketch& sketch, const SketchTarget& spline);

// Round the corner where the lines `a` and `b` meet (they must share an end point) with an arc of `radius`.  The sketch
// is solved first.  Both lines are shortened to the tangent points; the arc runs counter-clockwise from its start to
// its end around its centre and is tied to each line with a tangent constraint (at_b = the arc end that touches the
// line) and a driving radius.  The corner point goes away unless a constraint or another entity uses it; when it stays,
// the cut off part of each line stays as a construction line collinear with it, so the lines keep the place they had.
// horizontal / vertical (and the other constraints that hold for a shorter line) stay; lengths and other dimensions of
// the lines are dropped.  Refuses parallel lines, lines that share no point, and a radius that does not leave part of
// the shorter line (the message names the largest radius).  New ids: p<n> points, a<n> the arc, l<n> construction legs,
// c_<kind>_<n> constraints.
Sketch fillet_corner_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b, const Scalar& radius);

// As fillet_corner_rsketch, with a straight line from the point `distance` along `a` to the point `distance` along `b`
// (measured from the corner) instead of the arc.  The new line gets a driving length (the chord) and a driving angle to
// `a`.  `distance` must be shorter than the shorter line.  New ids: p<n> points, l<n> the chamfer line.
Sketch chamfer_corner_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                              const Scalar& distance);

// Bring geometry from another sketch (any plane) into `sketch` as reference geometry.  `source` is solved first and
// every point goes through the plane frames of both sketches (u = (P - origin) . x_axis, v = (P - origin) . y_axis).
// Points, lines, circles and arcs in a plane parallel to the target are copied (an arc keeps its counter-clockwise
// sense); geometry that projects to a line (a circle / arc in a perpendicular plane) or a point (a line along the
// target normal) is kept as a line / point; an oblique full circle becomes an ellipse; an oblique arc is refused.
// `entities` limits the source entities (ids; default: every line, circle, arc and free point -- ellipses and
// B-splines are skipped and reported in the notes of metadata "last_edit").  The copies are construction by default and
// fixed at their projected coordinates.  Ids: proj_<source sketch id>_<n> (lowest free n); the list of
// {source, entity, projected} is metadata "projections".
Sketch project_rsketch(const Sketch& sketch, const Sketch& source,
                       const std::optional<std::vector<std::string>>& entities = std::nullopt,
                       bool construction = true);

// The same for the edges of shapes (a Solid, Face, Shell, Wire, Edge or Compound; a Vertex is a point), in world
// coordinates.  Lines and circles / arcs project as above; any other edge named on its own (an Edge source) is refused,
// and one found inside a face, wire, shell, solid or compound is skipped with a note (so the boundary of a face comes
// in with all its lines and arcs: a sketch on the face can snap and be constrained to it). Ids: proj_shape_<n>; the
// entity of a projections entry is the topo id of the edge.
Sketch project_rsketch(const Sketch& sketch, const std::vector<Shape>& source, bool construction = true);

// Throws the structured project_rsketch error with `reason` (for binding layers that read the source argument).
[[noreturn]] void project_rsketch_refuse(const std::string& reason);

// What an edit did, by id: entities (points included) and constraints created, removed or changed between two sketches.
struct SketchDiff {
  std::vector<std::string> created, removed, changed;
  std::vector<std::string> created_constraints, removed_constraints, changed_constraints;
  Value to_value() const;
};
SketchDiff diff_sketch_rsketchdiff(const Sketch& before, const Sketch& after);

// Where the non-construction lines, circles and arcs of the solved sketch cross, away from every point:
// [{"at": [x, y], "entities": [a, b]}].  The crossings trim_rsketch cuts at; not recorded in the graph.
Value inspect_sketch_rsketchcrossings(const Sketch& sketch);

// ---- solving and promotion -----------------------------------------------------

// Solve a copy of the sketch; the input keeps no solve result.  strict=false
// returns conflicting / failed results instead of raising.
SketchSolveResult inspect_sketch_rsketchresult(const Sketch& sketch, const SketchSolveRequest& request = {});

// The profiles a solved sketch offers, in the index order make_face_from_sketch_rface / make_wire_from_sketch_rwire
// use:
// {"profiles": [{index, id, kind, closed, entity_ids, point_ids, reversed}], "unusable": [why an edge set is no
// profile]}.  Entities are named by id; the geometry is the solved sketch's.
Value inspect_sketch_rsketchprofiles(const Sketch& sketch, const SketchSolveRequest& request = {});

// Promote a profile (closed loop or open chain) to a wire, solving internally.
Wire make_wire_from_sketch_rwire(const Sketch& sketch, const SketchProfileId& profile = 0,
                                 const SketchSolveRequest& request = {});

// One face per region of the sketch: a closed outer loop minus the loops directly inside it (holes come by themselves;
// a loop inside a hole is the outer loop of another region).  `profiles` names the regions by their outer profile (an
// index of inspect_sketch_rsketchprofiles or a profile id); nullopt: every region, in profile order.  Each face is
// recorded as make_face_from_sketch_rface(sketch, outer, inner_profiles=holes).  Refuses an open chain, a hole and an
// unknown profile by name.
std::vector<Face> make_faces_from_sketch_rfacelist(
    const Sketch& sketch, const std::optional<std::vector<SketchProfileId>>& profiles = std::nullopt,
    const SketchSolveRequest& request = {});

// Promote an outer profile and optional hole profiles to a face.
Face make_face_from_sketch_rface(const Sketch& sketch, const SketchProfileId& profile = 0,
                                 const std::vector<SketchProfileId>& inner_profiles = {},
                                 const SketchSolveRequest& request = {});

// The legacy container's faces: one promoted face when the sketch has entities,
// else a face per closed wire.
std::vector<Face> sketch_to_faces(const Sketch& sketch);

}  // namespace scad
