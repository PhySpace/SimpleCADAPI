#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>

#include "internal.hpp"
#include "scad/core/error.hpp"

namespace scad {

void ShapeIndex::insert(const TopoDS_Shape& shape) {
  if (slots_.empty() || (keys_.size() + 1) * 2 > slots_.size()) {
    std::size_t capacity = slots_.empty() ? 16 : slots_.size() * 2;
    slots_.assign(capacity, 0);
    for (std::size_t i = 0; i < keys_.size(); ++i) {
      std::size_t at = std::hash<TopoDS_Shape>{}(keys_[i]) & (capacity - 1);
      while (slots_[at] != 0)
        at = (at + 1) & (capacity - 1);
      slots_[at] = static_cast<std::uint32_t>(i + 1);
    }
  }
  const std::size_t mask = slots_.size() - 1;
  std::size_t at = std::hash<TopoDS_Shape>{}(shape)&mask;
  while (slots_[at] != 0) {
    if (keys_[slots_[at] - 1].IsSame(shape))
      return;  // already indexed
    at = (at + 1) & mask;
  }
  keys_.push_back(shape);
  slots_[at] = static_cast<std::uint32_t>(keys_.size());
}

void ShapeIndex::build(const TopoDS_Shape& root, TopAbs_ShapeEnum type) {
  for (TopExp_Explorer ex(root, type); ex.More(); ex.Next())
    insert(ex.Current());
  keys_.shrink_to_fit();
}

int ShapeIndex::find(const TopoDS_Shape& shape) const {
  if (slots_.empty())
    return 0;
  const std::size_t mask = slots_.size() - 1;
  for (std::size_t at = std::hash<TopoDS_Shape>{}(shape)&mask; slots_[at] != 0; at = (at + 1) & mask)
    if (keys_[slots_[at] - 1].IsSame(shape))
      return static_cast<int>(slots_[at]);
  return 0;
}

std::string_view kind_name(Kind kind) noexcept {
  switch (kind) {
    case Kind::Vertex:
      return "vertex";
    case Kind::Edge:
      return "edge";
    case Kind::Wire:
      return "wire";
    case Kind::Face:
      return "face";
    case Kind::Shell:
      return "shell";
    case Kind::Solid:
      return "solid";
    case Kind::Compound:
      return "compound";
  }
  return "shape";
}

TopAbs_ShapeEnum to_topabs(Kind kind) noexcept {
  switch (kind) {
    case Kind::Vertex:
      return TopAbs_VERTEX;
    case Kind::Edge:
      return TopAbs_EDGE;
    case Kind::Wire:
      return TopAbs_WIRE;
    case Kind::Face:
      return TopAbs_FACE;
    case Kind::Shell:
      return TopAbs_SHELL;
    case Kind::Solid:
      return TopAbs_SOLID;
    case Kind::Compound:
      return TopAbs_COMPOUND;
  }
  return TopAbs_SHAPE;
}

Kind kind_of(const TopoDS_Shape& shape) {
  if (shape.IsNull())
    throw ValueError("shape is null");
  switch (shape.ShapeType()) {
    case TopAbs_VERTEX:
      return Kind::Vertex;
    case TopAbs_EDGE:
      return Kind::Edge;
    case TopAbs_WIRE:
      return Kind::Wire;
    case TopAbs_FACE:
      return Kind::Face;
    case TopAbs_SHELL:
      return Kind::Shell;
    case TopAbs_SOLID:
      return Kind::Solid;
    case TopAbs_COMPOUND:
      return Kind::Compound;
    default:
      break;
  }
  throw ValueError("unsupported shape type (compsolid); expected vertex, edge, wire, face, shell, solid or compound");
}

namespace {

Symbol topo_name(Kind kind, std::size_t index) {
  char text[32];
  const std::string_view name = kind_name(kind);
  name.copy(text, name.size());
  std::size_t n = name.size();
  text[n++] = '_';
  char digits[20];
  int count = 0;
  do {
    digits[count++] = static_cast<char>('0' + index % 10);
    index /= 10;
  } while (index != 0);
  while (count > 0)
    text[n++] = digits[--count];
  return Symbol(std::string_view(text, n));
}

}  // namespace

std::shared_ptr<Entity> Registry::acquire(Kind kind, const TopoDS_Shape& shape) {
  Table& table = tables_[static_cast<std::size_t>(kind)];
  if (!table.built) {
    table.map.build(root_, to_topabs(kind));
    table.by_index.resize(static_cast<std::size_t>(table.map.extent()));
    table.built = true;
  }
  const int index = table.map.find(shape);  // 1-based; 0 when absent
  if (index > 0) {
    auto& slot = table.by_index[static_cast<std::size_t>(index - 1)];
    if (!slot) {
      slot = std::make_shared<Entity>(kind, shape, topo_name(kind, static_cast<std::size_t>(index - 1)));
    }
    return slot;
  }
  // Not part of this root (a result handed in by an operator, say): number it
  // after the root's own entities of this kind.
  const auto found = table.foreign.find(shape);
  if (found != table.foreign.end())
    return found->second;
  const auto serial = static_cast<std::size_t>(table.map.extent()) + table.foreign.size();
  auto entity = std::make_shared<Entity>(kind, shape, topo_name(kind, serial));
  table.foreign.emplace(shape, entity);
  return entity;
}

std::shared_ptr<Entity> Registry::peek(Kind kind, const TopoDS_Shape& shape) {
  Table& table = tables_[static_cast<std::size_t>(kind)];
  if (!table.built)
    return nullptr;  // nothing of this kind was ever acquired
  const int index = table.map.find(shape);
  if (index > 0)
    return table.by_index[static_cast<std::size_t>(index - 1)];
  const auto found = table.foreign.find(shape);
  return found != table.foreign.end() ? found->second : nullptr;
}

bool Registry::contains(Kind kind, const TopoDS_Shape& shape) {
  Table& table = tables_[static_cast<std::size_t>(kind)];
  if (!table.built) {
    table.map.build(root_, to_topabs(kind));
    table.by_index.resize(static_cast<std::size_t>(table.map.extent()));
    table.built = true;
  }
  return table.map.find(shape) > 0;
}

const TopTools_IndexedDataMapOfShapeListOfShape& Registry::ancestors(Kind child, Kind parent) {
  for (const auto& table : ancestor_tables_)
    if (table->child == child && table->parent == parent)
      return table->map;
  auto table = std::make_unique<AncestorTable>();
  table->child = child;
  table->parent = parent;
  TopExp::MapShapesAndAncestors(root_, to_topabs(child), to_topabs(parent), table->map);
  ancestor_tables_.push_back(std::move(table));
  return ancestor_tables_.back()->map;
}

}  // namespace scad
