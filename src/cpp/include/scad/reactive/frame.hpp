// The frame graph a recording keeps (simplecadapi/params/frame.py): the
// coordinate system current when each operation was recorded.
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"

namespace scad::reactive {

struct FrameNode {
  std::string frame_id;
  Vec3 origin;
  Vec3 x_axis{1, 0, 0};
  Vec3 y_axis{0, 1, 0};
  Vec3 z_axis{0, 0, 1};
  std::optional<std::string> parent_frame_id;
  Value metadata = Value::object();

  bool operator==(const FrameNode& other) const;
};

// Frames by id; adding a frame replaces any with the same id.  Not thread-safe.
class FrameGraph {
 public:
  FrameNode ensure_frame(std::string frame_id, const Vec3& origin, const Vec3& x_axis, const Vec3& y_axis,
                         const Vec3& z_axis, std::optional<std::string> parent_frame_id = std::nullopt,
                         Value metadata = Value::object());
  const FrameNode& add(FrameNode node);

  std::size_t node_count() const noexcept { return nodes_.size(); }
  const FrameNode* get(std::string_view frame_id) const;

  Value to_value() const;
  static FrameGraph from_value(const Value& payload);

 private:
  std::vector<FrameNode> nodes_;  // insertion order, as Python's dict
  std::unordered_map<std::string, std::size_t> index_;
};

}  // namespace scad::reactive
