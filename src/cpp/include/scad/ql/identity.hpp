// Entity identity for QL results: same root, same entity -- never geometric equality.
//
// Two handles denote the same entity when they came from the same root and name
// the same topology (Shape::same_entity).  Use IdentitySet to deduplicate or
// intersect shape lists; topo_id() alone is not enough because it repeats across roots.
#pragma once

#include <functional>
#include <string>
#include <unordered_set>

#include "scad/topo/shape.hpp"

namespace scad::ql {

struct IdentityHash {
  std::size_t operator()(const Shape& s) const noexcept { return std::hash<std::string>{}(s.topo_id()); }
};

struct IdentityEqual {
  bool operator()(const Shape& a, const Shape& b) const noexcept { return a.same_entity(b); }
};

using IdentitySet = std::unordered_set<Shape, IdentityHash, IdentityEqual>;

}  // namespace scad::ql
