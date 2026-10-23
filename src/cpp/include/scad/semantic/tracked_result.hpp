// The result types shared between tracking (which makes them) and the tag
// projection / finalize pipeline (which consumes them).  Fixed early so the two
// can be written independently.
#pragma once

#include <map>
#include <optional>
#include <string>

#include "scad/core/value.hpp"
#include "scad/topo/delta.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// How much provenance an operation computes.  Graph = only what the recorded
// graph needs (standard-part factories use it for their intermediate steps).
enum class TrackingPolicy { Full, Graph };

TrackingPolicy current_tracking_policy() noexcept;

// RAII: set the policy for the current thread.
class TrackingPolicyScope {
 public:
  explicit TrackingPolicyScope(TrackingPolicy policy) noexcept;
  ~TrackingPolicyScope();
  TrackingPolicyScope(const TrackingPolicyScope&) = delete;
  TrackingPolicyScope& operator=(const TrackingPolicyScope&) = delete;

 private:
  TrackingPolicy previous_;
};

// Per-entity metadata keyed by topo_id (TrackedResult.delta_entries in Python).
using DeltaEntries = std::map<std::string, Value>;

// A tracked single-result operation (transform, extrude, fillet, ...).
struct TrackedResult {
  Shape shape;  // the result; its kind is the operator's output kind
  TopoDelta delta;
  DeltaEntries delta_entries;
};

// A tracked boolean.  `solid` is empty when the boolean produced no solid.
struct TrackedBooleanResult {
  std::optional<Solid> solid;
  TopoDelta delta;
  DeltaEntries delta_entries;
};

}  // namespace scad
