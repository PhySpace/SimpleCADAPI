// Rigid placements: a right-handed frame mapping child-local coordinates to parent
// coordinates (simplecadapi/product/placement.py), and the composition helpers the
// constraint solver is built from.
#pragma once

#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/product/semantic_value.hpp"

namespace scad::product {

class Placement : public SemanticValue {
 public:
  // The frame is canonical: the axes are normalised, must be orthogonal, and z = x cross y.
  // ValueError for a non-finite or zero axis, or axes that are not orthogonal.
  explicit Placement(Vec3 origin, Vec3 x_axis = {1, 0, 0}, Vec3 y_axis = {0, 1, 0});

  // A frame whose components are kept verbatim (durable boundaries): the axes must already
  // be unit, orthogonal and right-handed to within 2e-6.
  static Placement from_exact_frame(const Vec3& origin, const Vec3& x_axis, const Vec3& y_axis, const Vec3& z_axis);

  const Vec3& origin() const noexcept { return origin_; }
  const Vec3& x_axis() const noexcept { return x_; }
  const Vec3& y_axis() const noexcept { return y_; }
  const Vec3& z_axis() const noexcept { return z_; }

  Vec3 transform_point(const Vec3& point) const;
  Vec3 transform_vector(const Vec3& vector) const;
  // This frame applied after `child`'s: parent.compose(child) places a child frame in the parent's parent.
  Placement compose(const Placement& child) const;

  Value to_dict() const;

  // Frame equality; metadata and runtime do not take part.
  bool operator==(const Placement& other) const noexcept;

 private:
  struct Exact {};
  Placement(Exact, const Vec3& origin, const Vec3& x_axis, const Vec3& y_axis, const Vec3& z_axis);

  Vec3 origin_, x_, y_, z_;
};

Placement identity_placement();
Placement inverse_placement(const Placement& placement);
// inverse(base) composed with target: `target` seen from `base`.
Placement relative_placement(const Placement& base, const Placement& target);
Placement rotate_z_placement(double angle_degrees);
Placement translate_z_placement(double distance);

}  // namespace scad::product
