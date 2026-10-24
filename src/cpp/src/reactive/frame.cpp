#include "scad/reactive/frame.hpp"

namespace scad::reactive {

namespace {

Value vec_value(const Vec3& v) {
  Value out = Value::array();
  out.push_back(v.x);
  out.push_back(v.y);
  out.push_back(v.z);
  return out;
}

Vec3 vec_from(const Value* value, const Vec3& fallback) {
  if (value == nullptr || !value->is_array() || value->size() != 3) return fallback;
  const auto& a = value->as_array();
  return {a[0].as_double(), a[1].as_double(), a[2].as_double()};
}

}  // namespace

bool FrameNode::operator==(const FrameNode& other) const {
  return frame_id == other.frame_id && origin == other.origin && x_axis == other.x_axis && y_axis == other.y_axis &&
         z_axis == other.z_axis && parent_frame_id == other.parent_frame_id && metadata == other.metadata;
}

const FrameNode& FrameGraph::add(FrameNode node) {
  const auto found = index_.find(node.frame_id);
  if (found != index_.end()) {
    nodes_[found->second] = std::move(node);
    return nodes_[found->second];
  }
  index_.emplace(node.frame_id, nodes_.size());
  nodes_.push_back(std::move(node));
  return nodes_.back();
}

FrameNode FrameGraph::ensure_frame(std::string frame_id, const Vec3& origin, const Vec3& x_axis, const Vec3& y_axis,
                                   const Vec3& z_axis, std::optional<std::string> parent_frame_id, Value metadata) {
  return add(FrameNode{std::move(frame_id), origin, x_axis, y_axis, z_axis, std::move(parent_frame_id), std::move(metadata)});
}

const FrameNode* FrameGraph::get(std::string_view frame_id) const {
  const auto found = index_.find(std::string(frame_id));
  return found == index_.end() ? nullptr : &nodes_[found->second];
}

Value FrameGraph::to_value() const {
  Value nodes = Value::array();
  for (const FrameNode& node : nodes_) {
    Value item = Value::object();
    item.set("frame_id", node.frame_id);
    item.set("origin", vec_value(node.origin));
    item.set("x_axis", vec_value(node.x_axis));
    item.set("y_axis", vec_value(node.y_axis));
    item.set("z_axis", vec_value(node.z_axis));
    item.set("parent_frame_id", node.parent_frame_id ? Value(*node.parent_frame_id) : Value());
    item.set("metadata", node.metadata);
    nodes.push_back(std::move(item));
  }
  Value out = Value::object();
  out.set("nodes", std::move(nodes));
  return out;
}

FrameGraph FrameGraph::from_value(const Value& payload) {
  FrameGraph graph;
  const Value* nodes = payload.find("nodes");
  if (nodes == nullptr || !nodes->is_array()) return graph;
  for (const Value& item : nodes->as_array()) {
    if (!item.is_object()) continue;
    const Value* id = item.find("frame_id");
    if (id == nullptr) continue;
    FrameNode node;
    node.frame_id = id->is_string() ? id->as_string() : id->dump();
    node.origin = vec_from(item.find("origin"), {0, 0, 0});
    node.x_axis = vec_from(item.find("x_axis"), {1, 0, 0});
    node.y_axis = vec_from(item.find("y_axis"), {0, 1, 0});
    node.z_axis = vec_from(item.find("z_axis"), {0, 0, 1});
    if (const Value* parent = item.find("parent_frame_id"); parent != nullptr && parent->is_string()) {
      node.parent_frame_id = parent->as_string();
    }
    if (const Value* meta = item.find("metadata"); meta != nullptr && meta->is_object()) node.metadata = *meta;
    graph.add(std::move(node));
  }
  return graph;
}

}  // namespace scad::reactive
