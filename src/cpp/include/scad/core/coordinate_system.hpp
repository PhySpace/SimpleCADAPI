// CoordinateSystem and the workplane stack.
//
// Mirrors simplecadapi/core.py.  Like the Python original, the constructor
// normalizes x and y independently and derives z = normalize(x cross y); it
// does not re-orthogonalize y.  Operators read the active system with
// current_cs() and place their results through it.
#pragma once

#include <string>

#include "scad/core/vec.hpp"

namespace scad {

class CoordinateSystem {
 public:
  // World frame: origin 0, x = +X, y = +Y.
  CoordinateSystem();
  CoordinateSystem(const Vec3& origin, const Vec3& x_axis, const Vec3& y_axis);

  const Vec3& origin() const noexcept { return origin_; }
  const Vec3& x_axis() const noexcept { return x_; }
  const Vec3& y_axis() const noexcept { return y_; }
  const Vec3& z_axis() const noexcept { return z_; }

  // Local -> global.  Both reject non-finite input.
  Vec3 transform_point(const Vec3& local) const;
  Vec3 transform_vector(const Vec3& local) const;

  std::string to_string(int indent = 0) const;
  std::string repr() const;

 private:
  Vec3 origin_;
  Vec3 x_;
  Vec3 y_;
  Vec3 z_;
};

const CoordinateSystem& world_cs();

// The innermost active coordinate system (the world frame when no workplane is open).
const CoordinateSystem& current_cs();

// RAII: makes `cs` the current system for the lifetime of the object.  The
// stack is thread-local, so concurrent builds on different threads do not see
// each other's workplanes.  Not copyable or movable: its address is the scope.
class CoordinateSystemScope {
 public:
  explicit CoordinateSystemScope(CoordinateSystem cs);
  ~CoordinateSystemScope();
  CoordinateSystemScope(const CoordinateSystemScope&) = delete;
  CoordinateSystemScope& operator=(const CoordinateSystemScope&) = delete;

  const CoordinateSystem& cs() const noexcept { return cs_; }

 private:
  CoordinateSystem cs_;
};

// The workplane context manager: builds the frame from (origin, normal, x_dir)
// expressed in the *current* system, then pushes it.
class Workplane {
 public:
  Workplane(const Vec3& origin = {0, 0, 0}, const Vec3& normal = {0, 0, 1}, const Vec3& x_dir = {1, 0, 0});
  // The stack holds the address of cs_, so a Workplane never moves.
  Workplane(const Workplane&) = delete;
  Workplane& operator=(const Workplane&) = delete;
  ~Workplane();

  const CoordinateSystem& cs() const noexcept { return cs_; }
  std::string repr() const;
  std::string to_string(int indent = 0, bool show_coordinate_system = true) const;

  // Python `with` support: push on enter, pop on exit.  enter()/exit() must pair.
  void enter();
  void exit() noexcept;

 private:
  CoordinateSystem cs_;
  bool entered_ = false;
};

}  // namespace scad
