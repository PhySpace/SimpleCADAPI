#include "scad/kernel/membership.hpp"

#include <TopExp.hxx>

namespace scad::kernel {

const TopTools_IndexedMapOfShape& SubShapeIndex::of_type(TopAbs_ShapeEnum type) {
  const auto slot = static_cast<std::size_t>(type);
  if (!built_[slot]) {
    if (!root_.IsNull()) TopExp::MapShapes(root_, type, maps_[slot]);
    built_[slot] = true;
  }
  return maps_[slot];
}

bool SubShapeIndex::contains(const TopoDS_Shape& candidate) {
  if (candidate.IsNull() || root_.IsNull()) return false;
  if (root_.IsSame(candidate)) return true;
  return of_type(candidate.ShapeType()).Contains(candidate);
}

}  // namespace scad::kernel
