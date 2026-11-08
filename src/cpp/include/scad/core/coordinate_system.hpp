// CoordinateSystem and the workplane stack.
//
// Mirrors simplecadapi/core.py.  Like the Python original, the constructor
// normalizes x and y independently and derives z = normalize(x cross y); it
// does not re-orthogonalize y.  Operators read the active system with
// current_cs() and place their results through it.
#pragma once

#include <string>
#include <string_view>

#include "scad/core/value.hpp"
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

// Where the innermost active frame came from: the recorded node of the Workplane value that pushed it
// (its runtime "graph.id" / "graph.node_id" / "graph.output_slot").  A recorder writes it into the context of
// every operation made inside the workplane, so a replay can take the frame from the replayed workplane
// instead of the numbers frozen at recording time.
struct FrameSource {
  std::string graph_id;
  std::string node_id;
  int output_slot = 0;
};

// The source of the innermost active frame; nullptr for the world frame, a CoordinateSystemScope or a
// workplane that no recorder saw.
const FrameSource* current_frame_source();

// A workplane: a frame in world coordinates that is also the context manager making it the current system.
//
// It is a value: copies share nothing but the frame, it can be entered again after it is left (`with wp:`
// in several places), and it carries metadata / runtime dictionaries like the other recorded values, so the
// operation that made it (make_workplane_*_rworkplane) is its graph lineage.
class Workplane {
 public:
  // The frame from (origin, normal, x_dir) expressed in the *current* system.
  Workplane(const Vec3& origin = {0, 0, 0}, const Vec3& normal = {0, 0, 1}, const Vec3& x_dir = {1, 0, 0});
  // A workplane on an exact world frame (no current-system transform).
  static Workplane from_frame(const CoordinateSystem& cs);

  // A copy has the same frame, its own copies of the dictionaries, and is not entered.
  Workplane(const Workplane& other);
  Workplane& operator=(const Workplane&) = delete;
  ~Workplane();

  const CoordinateSystem& cs() const noexcept { return cs_; }
  const Vec3& origin() const noexcept { return cs_.origin(); }
  const Vec3& normal() const noexcept { return cs_.z_axis(); }
  const Vec3& x_dir() const noexcept { return cs_.x_axis(); }
  const Vec3& y_dir() const noexcept { return cs_.y_axis(); }
  // {"origin", "x_axis", "y_axis"}: the frame as a sketch plane mapping (world coordinates).
  Value plane_value() const;

  std::string repr() const;
  std::string to_string(int indent = 0, bool show_coordinate_system = true) const;

  // Python `with` support: push on enter, pop on exit.  enter()/exit() must pair; entering a workplane
  // that is already entered is a RuntimeError.
  void enter();
  void exit() noexcept;
  bool entered() const noexcept { return entered_; }

  void set_metadata(std::string key, Value value) const { metadata_.set(std::move(key), std::move(value)); }
  Value get_metadata(std::string_view key, Value fallback = {}) const;
  void set_runtime(std::string key, Value value) const { runtime_.set(std::move(key), std::move(value)); }
  Value get_runtime(std::string_view key, Value fallback = {}) const;
  const Value& metadata() const noexcept { return metadata_; }
  const Value& runtime() const noexcept { return runtime_; }

 private:
  struct Exact {};
  Workplane(Exact, const CoordinateSystem& cs);

  CoordinateSystem cs_;
  bool entered_ = false;
  mutable Value metadata_ = Value::object();
  mutable Value runtime_ = Value::object();
};

}  // namespace scad
