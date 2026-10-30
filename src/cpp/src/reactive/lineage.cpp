#include "scad/reactive/lineage.hpp"

#include <cctype>

namespace scad::reactive {

std::optional<Lineage> lineage_of(const Shape& shape) {
  const Value node = shape.get_runtime("graph.node_id");
  if (!node.is_string())
    return std::nullopt;
  Lineage out;
  out.node_id = node.as_string();
  const Value graph = shape.get_runtime("graph.id");
  if (graph.is_string())
    out.graph_id = graph.as_string();
  const Value slot = shape.get_runtime("graph.output_slot");
  if (slot.is_int())
    out.output_slot = static_cast<int>(slot.as_int());
  return out;
}

void set_lineage(Shape shape, const Lineage& lineage, std::string_view op) {
  shape.set_runtime("graph.id", lineage.graph_id);
  shape.set_runtime("graph.node_id", lineage.node_id);
  shape.set_runtime("graph.output_slot", lineage.output_slot);
  Value graph = Value::object();
  graph.set("graph_id", lineage.graph_id.empty() ? Value() : Value(lineage.graph_id));
  graph.set("node_id", lineage.node_id);
  graph.set("op", std::string(op));
  graph.set("output_slot", lineage.output_slot);
  shape.set_metadata("graph", std::move(graph));
}

void keep_topology_owner(Shape shape) {
  if (shape.get_runtime("topo.owner.node_id").is_string())
    return;
  const std::optional<Lineage> own = lineage_of(shape);
  if (!own)
    return;
  shape.set_runtime("topo.owner.graph_id", own->graph_id);
  shape.set_runtime("topo.owner.node_id", own->node_id);
  shape.set_runtime("topo.owner.slot", own->output_slot);
}

namespace {

// The recorded output a shape's contents belong to: its topology owner when a tag node re-attributed it.
std::optional<Lineage> topology_lineage(const Shape& shape) {
  const Value node = shape.get_runtime("topo.owner.node_id");
  if (node.is_string()) {
    Lineage out;
    out.node_id = node.as_string();
    const Value graph = shape.get_runtime("topo.owner.graph_id");
    if (graph.is_string())
      out.graph_id = graph.as_string();
    const Value slot = shape.get_runtime("topo.owner.slot");
    if (slot.is_int())
      out.output_slot = static_cast<int>(slot.as_int());
    return out;
  }
  return lineage_of(shape);
}

TopoRef parse_topo_ref(const Value& ref) {
  TopoRef out;
  const auto text = [&ref](const char* key) {
    const Value* v = ref.find(key);
    return v != nullptr && v->is_string() ? v->as_string() : std::string();
  };
  out.graph_id = text("graph_id");
  out.node_id = text("node_id");
  out.topo_id = text("topo_id");
  if (const Value* slot = ref.find("output_slot"); slot != nullptr && slot->is_int()) {
    out.output_slot = static_cast<int>(slot->as_int());
  }
  const std::string kind = text("kind");
  for (const Kind k : {Kind::Vertex, Kind::Edge, Kind::Wire, Kind::Face, Kind::Shell, Kind::Solid, Kind::Compound}) {
    std::string lowered = kind;
    for (char& c : lowered)
      c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if (kind_name(k) == lowered)
      out.kind = k;
  }
  return out;
}

// The nearest recorded output above `shape` through the containment links enumeration has made.
std::optional<Lineage> enclosing_lineage(const Shape& shape) {
  std::vector<Shape> level = shape.known_parents();
  for (int depth = 0; depth < 8 && !level.empty(); ++depth) {
    std::vector<Shape> next;
    for (const Shape& parent : level) {
      if (auto lineage = topology_lineage(parent))
        return lineage;
      for (Shape& above : parent.known_parents())
        next.push_back(std::move(above));
    }
    level = std::move(next);
  }
  return std::nullopt;
}

}  // namespace

std::optional<TopoRef> topo_ref_of(const Shape& shape) {
  const Value stamped = shape.get_runtime("topo.ref");
  if (stamped.is_object())
    return parse_topo_ref(stamped);
  // A recorded output refers to itself (the Python SDK stamps its root with a reference too).
  if (const std::optional<Lineage> own = topology_lineage(shape)) {
    return TopoRef{own->graph_id, own->node_id, own->output_slot, shape.kind(), shape.topo_id()};
  }
  const std::optional<Lineage> root = enclosing_lineage(shape);
  if (!root)
    return std::nullopt;
  return TopoRef{root->graph_id, root->node_id, root->output_slot, shape.kind(), shape.topo_id()};
}

void set_topo_ref(Shape shape, const TopoRef& ref) {
  shape.set_runtime("topo.ref", to_value(ref));
}

}  // namespace scad::reactive
