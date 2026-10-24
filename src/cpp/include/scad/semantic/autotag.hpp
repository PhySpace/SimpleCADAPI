// Evidence-gated semantic projection of tracking facts (topology/autotag.py).
//
// Given what an operation did to topology (a TopoDelta plus the per-entity
// witnesses the tracker computed), write onto the result:
//   * a typed `track` metadata envelope on every face and edge,
//   * `<kind>.<role>` bindings for kernel-proven output roles,
//   * lineage witnesses: which source tag bindings reach which result entity,
//   * projected bindings for user tags the tracker proved should follow a feature.
// Missing evidence stays "unknown": nothing is guessed from geometry.
//
// Operators do not call this directly; finalize_tracked (finalize.hpp) does.
#pragma once

#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "scad/semantic/tracked_result.hpp"
#include "scad/topo/delta.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// How a tracking witness names a sub-shape: its kernel id (`kernel_topo_id`, tracking.hpp),
// the identity hash of (TShape, Location) that is equal for every IsSame occurrence.  The
// recorder later resolves kernel ids to per-root ids ("face_3"); this layer works before that.
std::string topology_key(const Shape& shape);

// kernel id -> shape, over the shapes of one kind.  As in Python, the last shape added wins.
class TopologyIndex {
 public:
  void add(const Shape& shape);
  const Shape* find(std::string_view id) const;
  bool empty() const noexcept { return shapes_.empty(); }

 private:
  struct Hash {
    using is_transparent = void;
    std::size_t operator()(std::string_view s) const noexcept { return std::hash<std::string_view>{}(s); }
  };
  std::unordered_map<std::string, Shape, Hash, std::equal_to<>> shapes_;
};

struct TrackingContext {
  std::string op = "unknown";  // the public operator name ("make_cut_rsolid")
  // Every shape the operation consumed (source_solid, source_solids, source_shapes).
  std::vector<Shape> sources;
};

// apply_tracking_tags: returns `result` (tagged in place).
Shape apply_tracking_tags(Shape result, const TopoDelta& delta, const DeltaEntries& entries,
                          const TrackingContext& context);

// The DeltaEntries view of a delta's `entries` (_entries_from_delta): used when
// the tracker supplied no pre-aggregated entries.
DeltaEntries entries_from_delta(const TopoDelta& delta);

// "make_box_rsolid" -> "box", "op.cut" -> "cut" (_operation_alias).
std::string operation_alias(std::string_view op);

}  // namespace scad
