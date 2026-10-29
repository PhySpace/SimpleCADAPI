// Which entities a selector can see: the scope's own, and the ones bounding them.
//
// The tables below are the Python SDK's, case by case, because they are
// observable: ql.wires().resolve(solid) is empty (a solid has no wire children)
// while ql.faces().boundary("wire").resolve(solid) is not.
#include <iterator>

#include "internal.hpp"
#include "scad/core/error.hpp"

namespace scad::ql::detail {

namespace {

template <class T>
std::vector<Shape> widen(std::vector<T>&& items) {
  return std::vector<Shape>(std::make_move_iterator(items.begin()), std::make_move_iterator(items.end()));
}

bool has_faces(Kind kind) noexcept {
  return kind == Kind::Shell || kind == Kind::Solid || kind == Kind::Compound;
}
bool has_edges(Kind kind) noexcept {
  return kind == Kind::Wire || kind == Kind::Face || has_faces(kind);
}

std::vector<Shape> faces_of(const Shape& s) {
  switch (s.kind()) {
    case Kind::Shell:
      return widen(Shell(s).faces());
    case Kind::Solid:
      return widen(Solid(s).faces());
    case Kind::Compound:
      return widen(Compound(s).faces());
    default:
      return {};
  }
}

std::vector<Shape> edges_of(const Shape& s) {
  switch (s.kind()) {
    case Kind::Wire:
      return widen(Wire(s).edges());
    case Kind::Face:
      return widen(Face(s).edges());
    case Kind::Shell:
      return widen(Shell(s).edges());
    case Kind::Solid:
      return widen(Solid(s).edges());
    case Kind::Compound:
      return widen(Compound(s).edges());
    default:
      return {};
  }
}

}  // namespace

std::vector<Shape> dedupe(std::vector<Shape> items) {
  IdentitySet seen;
  seen.reserve(items.size());
  std::vector<Shape> out;
  out.reserve(items.size());
  for (Shape& item : items)
    if (seen.insert(item).second)
      out.push_back(std::move(item));
  return out;
}

bool is_traversal_kind(std::string_view kind) noexcept {
  return kind == "vertex" || kind == "edge" || kind == "wire" || kind == "face" || kind == "solid" ||
         kind == "compound";
}

std::vector<Shape> boundary_items(const Shape& item, std::string_view target_kind) {
  const Kind kind = item.kind();
  if (target_kind == "face")
    return faces_of(item);

  if (target_kind == "wire") {
    if (kind == Kind::Face)
      return widen(Face(item).wires());
    if (!has_faces(kind))
      return {};
    std::vector<Shape> wires;
    for (const Shape& face : faces_of(item))
      for (Shape& wire : boundary_items(face, "wire"))
        wires.push_back(std::move(wire));
    return dedupe(std::move(wires));
  }

  if (target_kind == "edge")
    return has_edges(kind) ? dedupe(edges_of(item)) : std::vector<Shape>{};

  if (target_kind == "vertex") {
    if (kind == Kind::Edge)
      return widen(Edge(item).vertices());
    std::vector<Shape> vertices;
    for (const Shape& edge : boundary_items(item, "edge"))
      for (Vertex& vertex : Edge(edge).vertices())
        vertices.push_back(std::move(vertex));
    return dedupe(std::move(vertices));
  }

  if (target_kind == "solid") {
    if (kind == Kind::Compound)
      return widen(Compound(item).solids());
    return kind == Kind::Solid ? std::vector<Shape>{item} : std::vector<Shape>{};
  }
  if (target_kind == "shell")
    return kind == Kind::Shell ? std::vector<Shape>{item} : std::vector<Shape>{};
  if (target_kind == "compound")
    return kind == Kind::Compound ? std::vector<Shape>{item} : std::vector<Shape>{};
  return {};
}

std::vector<Shape> traverse_items(const std::vector<Shape>& items, std::string_view target_kind) {
  std::vector<Shape> out;
  for (const Shape& item : items)
    for (Shape& bounded : boundary_items(item, target_kind))
      out.push_back(std::move(bounded));
  return dedupe(std::move(out));
}

std::vector<Shape> scope_items(const Scope& scope, std::string_view target_kind) {
  // A list scope is its own candidate set, whatever the kinds in it.
  if (scope.is_list())
    return scope.items();

  const Shape& shape = scope.shape();
  const Kind kind = shape.kind();
  if (kind_name(kind) == target_kind)
    return {shape};

  if (target_kind == "edge") {
    if (has_edges(kind))
      return edges_of(shape);
  } else if (target_kind == "face") {
    if (has_faces(kind))
      return faces_of(shape);
  } else if (target_kind == "solid") {
    if (kind == Kind::Compound)
      return widen(Compound(shape).solids());
  } else if (target_kind == "wire") {
    // The wires that are the scope's direct children: a face's, a shell's free boundaries.
    if (kind == Kind::Face)
      return widen(Face(shape).wires());
    if (kind == Kind::Shell)
      return widen(Shell(shape).wires());
    return {};
  } else if (target_kind == "vertex") {
    std::vector<Shape> vertices = kind == Kind::Edge ? widen(Edge(shape).vertices()) : boundary_items(shape, "vertex");
    if (!vertices.empty())
      return vertices;
  }
  throw TypeError("cannot resolve QL selector scope for target_kind=" + std::string(target_kind));
}

}  // namespace scad::ql::detail
