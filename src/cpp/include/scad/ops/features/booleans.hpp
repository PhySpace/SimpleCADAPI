// Boolean operators.
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "scad/topo/shape.hpp"

namespace scad {

struct UnionOptions {
  bool clean = true;                     // unify same-domain faces afterwards
  bool glue = false;                     // try OCC's glue optimisation first; a non-conclusive result is retried plain
  std::optional<double> tol;             // fuzzy tolerance; default scales with the operands' extent
  std::string tracking_policy = "full";  // "graph": record the node, compute no topology delta
};

// One manifold solid from `solids` (face contact or overlap).  Separated solids, and contact
// along an edge or a point only, are errors with the measured gap.  Error "union_rsolid".
Solid union_rsolid(const std::vector<Solid>& solids, const UnionOptions& options = {});

struct CutOptions {
  bool skip_non_intersecting = true;  // a tool that does not meet the body is ignored
  std::string tracking_policy = "full";
  // cut_rsolid_list: order the pieces by centroid (x, then y, then z) instead of kernel order, so piece i is the same
  // piece on every OCCT version.  Recorded as params.piece_order = "centroid" only when set.
  bool order_pieces = false;
};

// What a cut that may split leaves: one Solid, or (`solid` empty) every piece, ordered by centroid.
struct CutOutcome {
  std::optional<Solid> solid;
  std::vector<Solid> pieces;
};

// The first solid minus every other.  Error "cut_rsolid".
Solid cut_rsolid(const std::vector<Solid>& solids, const CutOptions& options = {});

// The same cut, keeping every piece: a cut that splits the body (a slot through a bar) returns each part, and one that
// consumes the body returns an empty list.  cut_rsolid refuses such a result instead of dropping parts.
// Error "cut_rsolid_list"; recorded as make_cut_rsolid_list.
std::vector<Solid> cut_rsolid_list(const std::vector<Solid>& solids, const CutOptions& options = {});

// cut_rsolid that accepts a split: a one-piece result is exactly cut_rsolid (same record); a split is
// cut_rsolid_list with order_pieces (recorded as make_cut_rsolid_list).  An empty result is still an error.
CutOutcome cut_rsolid_keep_split(const std::vector<Solid>& solids, const CutOptions& options = {});

// The overlap of all `solids`.  Error "intersect_rsolid".
Solid intersect_rsolid(const std::vector<Solid>& solids);

// The error a non-Solid argument of union_rsolid / cut_rsolid / intersect_rsolid raises
// (a binding that flattens Python arguments throws it for an item that is not a solid).
[[noreturn]] void reject_boolean_operand(std::string_view operation);

// The error a non-Face argument of a 2D boolean raises (for a binding that receives a Python object).
[[noreturn]] void reject_face_operand(std::string_view operation, std::string_view name);

// A set boolean ("cut", "intersect", "union") of two body groups; every result solid is kept
// (possibly several, possibly none).  Recorded as make_boolean_rsolidlist.
std::vector<Solid> boolean_rsolidlist(const std::vector<Solid>& left, const std::vector<Solid>& right,
                                      std::string_view operation);

// 2D booleans of faces; the result must be exactly one face.
// Each argument must be a Face (an Error "make_2d_*_rface" otherwise).
Face make_2d_cut_rface(const Shape& body, const Shape& tool);
Face make_2d_union_rface(const Shape& face_a, const Shape& face_b);
Face make_2d_intersect_rface(const Shape& face_a, const Shape& face_b);

}  // namespace scad
