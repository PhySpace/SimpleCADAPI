// Operation tracking: OCCT algorithm history -> TopoDelta (topology/tracking.py).
//
// Each function builds a result with the OCCT algorithm that Python's tracked_*
// function uses and asks that algorithm's history (Modified / Generated /
// IsDeleted, FirstShape / LastShape, SectionEdges) what became of every input
// sub-shape.  The answer is a TopoDelta, plus the per-entity witness table
// `delta_entries` that the tag projection reads.  Operators call these instead
// of the raw builders, then hand `delta`/`delta_entries` to the finalize layer.
//
// Identity.  A delta names shapes by their *kernel id*, `kernel_topo_id()`:
// the hash of (TShape, Location), orientation ignored, so one sub-shape has the
// same id as an input face and as the result face it survives as (the analogue
// of `_topo_id` in Python).  An id is only meaningful while the shape it came
// from is alive; the recorder resolves kernel ids to stable per-root ids
// ("face_3") and rebinds the temporary graph/node ids (see below) when it
// records the operation.  The ids of refs a tracked_* function emits are
// temporary tracking ids "g_<8 hex>" / "n_<8 hex>" (is_temporary_tracking_ref),
// exactly as in Python: they are resolved or dropped, never kept.
//
// Policy.  Under TrackingPolicy::Graph (TrackingPolicyScope) the face/edge
// history is not queried at all -- no preserved/modified/generated/deleted
// lists, no entries, no `*.side`-style history roles -- but the kernel-native
// roles that cost nothing (box faces, FirstShape/LastShape caps, ...) are still
// reported, as in Python.  Standard-part factories use Graph for their many
// intermediate solids.
//
// Errors.  Failures are ValueError with the Python text ("Fillet failed: OCC
// build did not complete"); OCCT exceptions leave as KernelError.  Callers wrap
// them with their ErrorSpec via `guarded`.
//
// Cost.  History is indexed once per call (hash maps keyed on IsSame), never
// searched linearly; the result is built once and shared by reference.
#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <BRepTools_History.hxx>
#include <TopoDS_Shape.hxx>

#include "scad/core/vec.hpp"
#include "scad/kernel/builders.hpp"  // kernel::Axes3
#include "scad/semantic/tracked_result.hpp"
#include "scad/topo/delta.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// ---------------------------------------------------------------------------
// Identity helpers
// ---------------------------------------------------------------------------

// `_topo_id`: the kernel identity of `shape` as a decimal string.  Equal for
// every IsSame occurrence of one sub-shape, whatever its orientation.
std::string kernel_topo_id(const TopoDS_Shape& shape);

// True for the "g_xxxxxxxx" / "n_xxxxxxxx" ids tracking puts on its refs: they
// stand for "this operation" until the recorder binds real ones.
bool is_temporary_tracking_ref(const TopoRef& ref) noexcept;

// ---------------------------------------------------------------------------
// Primitives (operators: make_box_rsolid, make_cylinder_rsolid, make_cone_rsolid)
// ---------------------------------------------------------------------------

// tracked_box.  `corner` is the box's minimum corner; with `axes` the box is
// built in that frame and `corner` is its origin in global coordinates (the
// bottom face centre shifted by half the width/height).  Roles on faces:
// box.bottom/top/front/back/left/right.  No history entries.
TrackedResult tracked_box(const Vec3& corner, double width, double height, double depth,
                          const std::optional<kernel::Axes3>& axes = std::nullopt);

// tracked_cylinder.  `origin` is the base circle centre, `axis` the direction.
// Roles: cylinder.start/end/side (faces), cylinder.start_boundary/end_boundary/seam (edges).
TrackedResult tracked_cylinder(const Vec3& origin, const Vec3& axis, double radius, double height);

// tracked_cone.  Roles: cone.start, cone.end (only when top_radius > 0),
// cone.side (faces), cone.start_boundary/end_boundary/seam (edges).
TrackedResult tracked_cone(const Vec3& origin, const Vec3& axis, double bottom_radius, double top_radius,
                           double height);

// ---------------------------------------------------------------------------
// Transforms (operators: make_translate_rshape, make_rotate_rshape, make_mirror_rshape)
// ---------------------------------------------------------------------------

// tracked_translate.  Every face is "modified" with derivation "continuation".
TrackedResult tracked_translate(const Solid& shape, const Vec3& vector);
// tracked_rotate.  `angle_degrees` about `axis` through `origin`.
TrackedResult tracked_rotate(const Solid& shape, double angle_degrees, const Vec3& axis = {0, 0, 1},
                             const Vec3& origin = {0, 0, 0});
// tracked_mirror.  Mirror through the plane (`plane_origin`, `plane_normal`).
TrackedResult tracked_mirror(const Solid& shape, const Vec3& plane_origin, const Vec3& plane_normal);

// ---------------------------------------------------------------------------
// Sweeps of a profile (operators: extrude_rsolid, revolve_rsolid, loft_rsolid,
// sweep_rsolid, twisted_sweep_rsolid)
// ---------------------------------------------------------------------------

// tracked_extrude.  History is queried on the profile's *edges* (origin_role
// "profile"); each generated side face carries role extrusion.side with the
// profile edge as its parent.  Roles extrusion.start / extrusion.end are the
// first/last shapes of the prism.  ValueError for a zero direction.
TrackedResult tracked_extrude(const Face& profile, const Vec3& direction, double distance);

// tracked_revolve.  As extrude: revolution.side / .start / .end.
TrackedResult tracked_revolve(const Face& profile, const Vec3& axis, const Vec3& origin, double angle_degrees);

// tracked_loft.  `profiles` are Wires or Vertices (TypeError otherwise), at least
// two (ValueError; the kernel would crash on one); roles
// loft.side (per profile edge, origin_role "profile_<index>") and loft.start /
// loft.end on the caps.
TrackedResult tracked_loft(const std::vector<Shape>& profiles, bool ruled = false);

// tracked_sweep.  ValueError when the profile has inner wires.  Roles sweep.side
// / sweep.start / sweep.end.
TrackedResult tracked_sweep(const Face& profile, const Wire& path, bool is_frenet = false);

// tracked_twisted_sweep.  Sweeps every wire of the planar `profile` along the
// line (`origin`, `axis`, `distance`) while rotating by `twist_angle` degrees,
// then sews the walls and two caps into a solid.  Roles twisted_sweep.side /
// .start / .end; the result's metadata "twisted_sweep.kernel" records the
// approximation error.  No history entries (the solid is sewn, not swept).
TrackedResult tracked_twisted_sweep(const Face& profile, const Vec3& axis, const Vec3& origin, double distance,
                                    double twist_angle, double guide_radius);

// ---------------------------------------------------------------------------
// Local features (operators: fillet_rsolid, chamfer_rsolid, shell_rsolid)
// ---------------------------------------------------------------------------

// tracked_fillet.  Face history of the solid (origin_role "body"), then the
// contours OCCT actually filleted (origin_role "contour_edge"; generated
// edges carry role fillet.patch).
TrackedResult tracked_fillet(const Solid& solid, const std::vector<Edge>& edges, double radius);

// tracked_chamfer.  `distance2` makes the chamfer asymmetric and then needs one
// (face1, face2) pair per edge -- face1 takes `distance` -- else ValueError.
// Generated contour edges carry role chamfer.patch.
TrackedResult tracked_chamfer(const Solid& solid, const std::vector<Edge>& edges, double distance,
                              std::optional<double> distance2 = std::nullopt,
                              const std::vector<std::pair<Face, Face>>& edge_face_pairs = {});

// tracked_shell.  Hollow `solid` inward by `thickness`, removing
// `faces_to_remove`.  Roles on the result: shell.body_face, shell.offset_face,
// shell.closing_descendant (faces) and shell.wall (edges).
TrackedResult tracked_shell(const Solid& solid, const std::vector<Face>& faces_to_remove, double thickness,
                            double tol = 1e-6);

// ---------------------------------------------------------------------------
// Booleans (operators: cut_rsolid, union_rsolid, intersect_rsolid)
// ---------------------------------------------------------------------------

// tracked_cut.  Face history of body ("body") and tool ("tool"), plus the
// section edges.  `solid` of the result is the *first* solid of the kernel's
// result, empty when the cut left none; membership is judged against the whole
// kernel result.  ValueError when the algorithm did not complete.
TrackedBooleanResult tracked_cut(const Solid& body, const Solid& tool);

// tracked_union: a two-solid fuse with `track_union_history` on top.  ValueError
// unless the fuse yields exactly one solid.  Glue is opt-in (see kernel::fuse_shapes_with_history).
TrackedBooleanResult tracked_union(const Solid& body, const Solid& tool, bool glue = false, double tol = 1e-7);

// track_union_history: the delta of an N-ary union already performed with
// kernel::fuse_shapes_with_history(solids, ..., clean).  Input i has origin
// role "body", "tool", "tool_2", "tool_3", ...  `section_edges` are those the
// kernel reported (the ones not in the result are dropped).  ValueError for < 2 solids.
TrackedBooleanResult track_union_history(const std::vector<Solid>& solids, const Solid& result_solid,
                                         const BRepTools_History& history,
                                         const std::vector<TopoDS_Shape>& section_edges = {});

// tracked_intersect.
TrackedBooleanResult tracked_intersect(const Solid& body, const Solid& tool);

namespace tracking {
// How many topology-history queries the tracked operations have made in this process.  A graph-policy
// operation makes none: this is how that is observed (the SDK's tests patch a Python helper instead).
std::size_t history_query_count() noexcept;
}  // namespace tracking

}  // namespace scad
