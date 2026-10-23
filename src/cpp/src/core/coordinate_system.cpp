#include "scad/core/coordinate_system.hpp"

#include <cmath>
#include <cstdio>
#include <vector>

#include "scad/core/error.hpp"

namespace scad {

namespace {

const ErrorSpec& normalize_spec() {
  static const ErrorSpec spec{
      "CoordinateSystem._normalize",
      "A zero-length vector cannot be normalized.",
      {"The input vector is exactly (0, 0, 0).",
       "The input values collapsed to zero after numeric conversion."},
      {"Provide a non-zero direction vector.", "Check upstream calculations that produce this vector."}};
  return spec;
}

const ErrorSpec& construct_spec() {
  static const ErrorSpec spec{
      "CoordinateSystem.__init__",
      "Failed to create a coordinate system.",
      {"One of the origin or axis values is not a valid 3D numeric vector.",
       "One of the axis vectors is zero-length or cannot be normalized."},
      {"Pass origin, x_axis, and y_axis as 3-element numeric tuples or arrays.",
       "Make sure x_axis and y_axis are non-zero vectors.",
       "If you build axes dynamically, print the vectors before constructing the coordinate system."}};
  return spec;
}

const ErrorSpec& point_spec() {
  static const ErrorSpec spec{
      "CoordinateSystem.transform_point",
      "The point contains non-finite numeric values.",
      {"A previous computation produced NaN or infinity.",
       "The point was assembled from invalid expression results."},
      {"Inspect the upstream values used to build the point.",
       "Replace NaN or infinity with finite numeric coordinates before calling this API."}};
  return spec;
}

const ErrorSpec& vector_spec() {
  static const ErrorSpec spec{
      "CoordinateSystem.transform_vector",
      "The vector contains non-finite numeric values.",
      {"A previous computation produced NaN or infinity.",
       "The direction vector was derived from invalid geometry."},
      {"Inspect the upstream direction calculation.",
       "Ensure all vector components are finite numbers before calling this API."}};
  return spec;
}

Vec3 normalize_or_raise(const Vec3& v) {
  const double n = v.norm();
  if (n == 0.0) raise_harness_error(normalize_spec(), "vector=" + to_string(v));
  return v / n;
}

std::string fixed3(const Vec3& v) {
  char buf[128];
  std::snprintf(buf, sizeof buf, "[%.3f, %.3f, %.3f]", v.x, v.y, v.z);
  return buf;
}

// Thread-local stack of active systems.  The bottom entry (the world frame)
// is never popped.
std::vector<const CoordinateSystem*>& cs_stack() {
  thread_local std::vector<const CoordinateSystem*> stack;
  return stack;
}

}  // namespace

CoordinateSystem::CoordinateSystem() : origin_{0, 0, 0}, x_{1, 0, 0}, y_{0, 1, 0}, z_{0, 0, 1} {}

CoordinateSystem::CoordinateSystem(const Vec3& origin, const Vec3& x_axis, const Vec3& y_axis)
    : origin_(origin) {
  try {
    if (!origin.is_finite() || !x_axis.is_finite() || !y_axis.is_finite())
      throw ValueError("origin and axes must be finite");
    x_ = normalize_or_raise(x_axis);
    y_ = normalize_or_raise(y_axis);
    z_ = normalize_or_raise(x_.cross(y_));
  } catch (const Error&) {
    throw;
  } catch (const std::exception& e) {
    raise_harness_error(construct_spec(), e);
  }
}

Vec3 CoordinateSystem::transform_point(const Vec3& local) const {
  if (!local.is_finite()) raise_harness_error(point_spec(), "point=" + scad::to_string(local));
  return origin_ + x_ * local.x + y_ * local.y + z_ * local.z;
}

Vec3 CoordinateSystem::transform_vector(const Vec3& local) const {
  if (!local.is_finite()) raise_harness_error(vector_spec(), "vector=" + scad::to_string(local));
  return x_ * local.x + y_ * local.y + z_ * local.z;
}

std::string CoordinateSystem::to_string(int indent) const {
  const std::string pad(static_cast<std::size_t>(indent) * 2, ' ');
  std::string out = pad + "CoordinateSystem:\n";
  out += pad + "  origin: " + fixed3(origin_) + "\n";
  out += pad + "  x_axis: " + fixed3(x_) + "\n";
  out += pad + "  y_axis: " + fixed3(y_) + "\n";
  out += pad + "  z_axis: " + fixed3(z_);
  return out;
}

std::string CoordinateSystem::repr() const {
  return "CoordinateSystem(origin=" + scad::to_string(origin_) + ", x_axis=" + scad::to_string(x_) +
         ", y_axis=" + scad::to_string(y_) + ")";
}

const CoordinateSystem& world_cs() {
  static const CoordinateSystem world;
  return world;
}

const CoordinateSystem& current_cs() {
  const auto& stack = cs_stack();
  return stack.empty() ? world_cs() : *stack.back();
}

CoordinateSystemScope::CoordinateSystemScope(CoordinateSystem cs) : cs_(std::move(cs)) {
  cs_stack().push_back(&cs_);
}

CoordinateSystemScope::~CoordinateSystemScope() { cs_stack().pop_back(); }

namespace {

CoordinateSystem workplane_frame(const Vec3& origin, const Vec3& normal, const Vec3& x_dir) {
  const CoordinateSystem& current = current_cs();
  const Vec3 global_origin = current.transform_point(origin);
  Vec3 global_x = current.transform_vector(x_dir);
  Vec3 global_normal = current.transform_vector(normal);
  global_normal = normalize_or_raise(global_normal);

  Vec3 global_y = global_normal.cross(global_x);
  const double y_norm = global_y.norm();
  if (y_norm < 1e-10) {
    // x_dir is parallel to the normal: pick any perpendicular.
    const Vec3 temp_x = std::abs(global_normal.x) < 0.9 ? Vec3{1, 0, 0} : Vec3{0, 1, 0};
    global_y = global_normal.cross(temp_x);
    global_y = global_y / global_y.norm();
    global_x = global_y.cross(global_normal);
    global_x = global_x / global_x.norm();
  } else {
    global_y = global_y / y_norm;
    global_x = global_y.cross(global_normal);
    global_x = global_x / global_x.norm();
  }
  return CoordinateSystem(global_origin, global_x, global_y);
}

// Workplane::enter() needs somewhere stable to point the stack at.  A
// Workplane owns its frame by value, and entered workplanes are not moved.
}  // namespace

Workplane::Workplane(const Vec3& origin, const Vec3& normal, const Vec3& x_dir)
    : cs_(workplane_frame(origin, normal, x_dir)) {}

Workplane::~Workplane() { exit(); }

void Workplane::enter() {
  if (entered_) throw RuntimeError("Workplane is already entered");
  cs_stack().push_back(&cs_);
  entered_ = true;
}

void Workplane::exit() noexcept {
  if (!entered_) return;
  auto& stack = cs_stack();
  if (!stack.empty()) stack.pop_back();
  entered_ = false;
}

std::string Workplane::repr() const {
  return "SimpleWorkplane(origin=" + scad::to_string(cs_.origin()) +
         ", normal=" + scad::to_string(cs_.z_axis()) + ")";
}

std::string Workplane::to_string(int indent, bool show_coordinate_system) const {
  const std::string pad(static_cast<std::size_t>(indent) * 2, ' ');
  std::string out = pad + "SimpleWorkplane:";
  if (show_coordinate_system) {
    out += "\n" + pad + "  coordinate_system:\n" + cs_.to_string(indent + 2);
  }
  return out;
}

}  // namespace scad
