// Exact sub-shape membership: "is this shape part of that one?"
//
// The Python SDK answers by walking the whole shape for every query, which makes
// a history pass quadratic.  Here each shape type is mapped once, on first use,
// into an indexed map hashed on (TShape, Location) -- the IsSame identity -- so a
// query is a hash lookup.
#pragma once

#include <array>

#include <TopAbs_ShapeEnum.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS_Shape.hxx>

namespace scad::kernel {

class SubShapeIndex {
 public:
  explicit SubShapeIndex(TopoDS_Shape root) : root_(std::move(root)) {}

  const TopoDS_Shape& root() const noexcept { return root_; }

  // True when `candidate` is the root itself or one of its sub-shapes (IsSame
  // identity: orientation is ignored).  A null candidate is never a member.
  bool contains(const TopoDS_Shape& candidate);

  // Every distinct sub-shape of `type`, in TopExp_Explorer first-seen order.
  const TopTools_IndexedMapOfShape& of_type(TopAbs_ShapeEnum type);

 private:
  TopoDS_Shape root_;
  std::array<TopTools_IndexedMapOfShape, TopAbs_SHAPE + 1> maps_;
  std::array<bool, TopAbs_SHAPE + 1> built_{};
};

}  // namespace scad::kernel
