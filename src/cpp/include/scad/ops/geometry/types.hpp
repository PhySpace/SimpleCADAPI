// Argument types shared by the geometry operators.
//
// The Python operators take `ScalarLike` wherever a number is expected and tuples of
// them for points; these are the C++ spellings.  An operator evaluates its arguments
// once (evaluate_scalar / evaluate_point) and hands the original `Scalar`s to the
// recorder, so a parameter edit can rerun just that operation.
#pragma once

#include <array>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/vec.hpp"

namespace scad {

// A 3D point or direction whose coordinates may be symbolic.
using Scalar3 = std::array<Scalar, 3>;
// A point of 2 or 3 coordinates (spline poles may omit z).
using ScalarPoint = std::vector<Scalar>;
using ScalarList = std::vector<Scalar>;
using OptionalString = std::optional<std::string>;

// `evaluate_value` of a tuple: every coordinate evaluated, ValueError when one is not finite.
// `label` names the argument in the message.
Vec3 evaluate_point(const Scalar3& point, std::string_view label = "point");

// A point of literal coordinates as a Scalar3, for defaults and C++ callers.
inline Scalar3 scalar3(double x, double y, double z) { return {Scalar(x), Scalar(y), Scalar(z)}; }
inline Scalar3 scalar3(const Vec3& v) { return scalar3(v.x, v.y, v.z); }

}  // namespace scad
