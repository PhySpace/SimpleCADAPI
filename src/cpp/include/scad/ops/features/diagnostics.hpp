// Why a feature operator failed (operators/_diagnostics.py): the geometric facts behind a
// fillet, chamfer, boolean or loft failure, found by re-measuring the operands once the
// operation has failed.
//
// Every entry is best effort: a probe that cannot decide says nothing, and a diagnosis
// never replaces the error it explains.  Unlike the Python SDK none of them renders an
// evidence image (the measurements and repair lines carry the same facts as text).
#pragma once

#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// A classified fillet / chamfer failure.
struct BlendDiagnosis {
  // "tangent_adjacent_faces" | "sliver_edges_in_selection" | "size_exceeds_face" |
  // "partial_smooth_chain_on_periodic_face" | "blends_tangency_critical" | "vertex_blend_conflict"
  std::string failure_kind;
  std::string what_happened;
  std::vector<std::string> possible_causes;
  std::vector<ErrorMeasurement> measurements;
  std::vector<std::string> repair;
};

// Does the blend succeed on this one edge alone?  The per-edge diagnostic rerun.
using BlendRetry = std::function<bool(const Edge&)>;

// Classify why blending `edges` of `solid` by `size_value` failed.  Probe order, cheapest
// explanation first: sliver edges, tangent faces, size against the room on adjacent faces,
// a partially selected smooth chain, then (via `retry_single`, up to 64 edges) interaction
// between blends and corner conflicts.  `operation_kind` is "fillet" or "chamfer".
std::optional<BlendDiagnosis> diagnose_blend_failure(const Solid& solid, const std::vector<Edge>& edges,
                                                     double size_value, std::string_view operation_kind,
                                                     const BlendRetry& retry_single = {});

// The kernel handed back geometry no blend can produce.
class BlendVolumeViolation : public ValueError {
 public:
  using ValueError::ValueError;
};

// Exit check of a blend: an all-convex blend may only remove material.  Throws
// BlendVolumeViolation, naming the measured volumes, for an empty result or a convex blend
// that grew the solid.  Volumes that cannot be measured pass.
void assert_blend_volume_monotonic(const Solid& source, const Solid& result, std::string_view operation_kind,
                                   std::optional<double> size_value, const std::vector<Edge>& edges);

// A classified boolean failure.
struct BooleanDiagnosis {
  std::string failure_kind;  // "disjoint" | "non_manifold_contact"
  std::string what_happened;
  std::vector<std::string> possible_causes;
  std::vector<ErrorMeasurement> measurements;
  std::vector<std::string> repair;
  std::vector<Solid> evidence_shapes;  // the two operands the diagnosis is about, in order
  std::string evidence_caption;
};

// Why `operands` do not combine: separated (the nearest pair across clusters of operands
// within `effective_tol` of each other) or touching without volume.  `operation_kind` is
// "union", "cut" or "intersect".
std::optional<BooleanDiagnosis> diagnose_boolean_failure(const std::vector<Solid>& operands,
                                                         std::optional<double> effective_tol,
                                                         std::string_view operation_kind = "union");

// Re-read the loft `sections` after the kernel failed and, when they explain it (coincident
// stations, differing edge counts, open wires, out-of-order stations), throw the Error that
// says so.  Returns silently otherwise.
void raise_loft_failure_if_diagnosed(const std::vector<Shape>& sections, std::string_view operation);

}  // namespace scad
