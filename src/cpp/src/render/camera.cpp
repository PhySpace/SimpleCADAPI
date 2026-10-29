#include <algorithm>
#include <cmath>
#include <map>

#include "scad/core/error.hpp"
#include "scad/render/render.hpp"

namespace scad::render {

void Bounds::add(const Vec3& p) {
  if (!valid) {
    min = max = p;
    valid = true;
    return;
  }
  min = {std::min(min.x, p.x), std::min(min.y, p.y), std::min(min.z, p.z)};
  max = {std::max(max.x, p.x), std::max(max.y, p.y), std::max(max.z, p.z)};
}

void Bounds::add(const Bounds& other) {
  if (!other.valid)
    return;
  add(other.min);
  add(other.max);
}

double Bounds::span() const {
  const Vec3 s = spans();
  return std::max({s.x, s.y, s.z});
}

Camera::Projected Camera::project(const Vec3& p) const {
  const Vec3 d = p - target;
  const double u = d.dot(right) / (2.0 * half_height * aspect);
  const double v = d.dot(up) / (2.0 * half_height);
  return {0.5 + u, 0.5 - v, d.dot(forward)};
}

std::pair<double, double> view_preset(std::string_view name) {
  static const std::map<std::string, std::pair<double, double>, std::less<>> presets{
      {"iso", {25.0, 35.0}},         {"isometric", {25.0, 35.0}},  {"top", {90.0, 0.0}},
      {"bottom", {-90.0, 0.0}},      {"front", {0.0, -90.0}},      {"back", {0.0, 90.0}},
      {"left", {0.0, 180.0}},        {"right", {0.0, 0.0}},        {"front_right", {20.0, -45.0}},
      {"front_left", {20.0, 135.0}}, {"rear_right", {20.0, 45.0}}, {"rear_left", {20.0, -135.0}}};
  std::string token(name);
  const auto b = token.find_first_not_of(" \t\n");
  const auto e = token.find_last_not_of(" \t\n");
  token = b == std::string::npos ? "" : token.substr(b, e - b + 1);
  std::transform(token.begin(), token.end(), token.begin(), [](unsigned char c) { return std::tolower(c); });
  const auto it = presets.find(token);
  if (it == presets.end())
    throw ValueError("Unsupported view preset: " + std::string(name));
  return it->second;
}

std::pair<double, double> auto_view(const Vec3& spans) {
  return {spans.z <= std::max(spans.x, spans.y) ? 22.0 : 35.0, spans.x >= spans.y ? 35.0 : 125.0};
}

Camera fit_camera(double elevation_deg, double azimuth_deg, const Bounds& bounds, double aspect,
                  const std::optional<Vec3>& view_up, double zoom) {
  if (!(aspect > 0.0) || !(zoom > 0.0))
    throw ValueError("fit_camera: aspect and zoom must be positive");
  const Vec3 center = bounds.valid ? bounds.center() : Vec3{};
  const Vec3 spans = bounds.valid ? bounds.spans() : Vec3{};
  const double el = elevation_deg * kPi / 180.0;
  const double az = azimuth_deg * kPi / 180.0;
  const Vec3 dir{std::cos(el) * std::cos(az), std::cos(el) * std::sin(az), std::sin(el)};
  Vec3 up_hint;
  if (view_up)
    up_hint = *view_up;
  else if (std::abs(dir.z) > 0.95)
    up_hint = {0, 1, 0};
  else
    up_hint = {0, 0, 1};

  Camera cam;
  cam.target = center;
  cam.forward = -dir;
  Vec3 right = cam.forward.cross(up_hint);
  if (right.norm() < 1e-12)
    right = cam.forward.cross(Vec3{0, 1, 0});
  if (right.norm() < 1e-12)
    right = cam.forward.cross(Vec3{1, 0, 0});
  cam.right = right.normalized();
  cam.up = cam.right.cross(cam.forward).normalized();
  cam.aspect = aspect;
  // vtkRenderer::ResetCamera in parallel projection: scale = bounding radius, divided by the aspect
  // for portrait viewports; the SDK then Zoom(0.92)s.
  double radius = 0.5 * spans.norm();
  if (radius <= 0.0)
    radius = 1.0;
  const double scale = aspect >= 1.0 ? radius : radius / aspect;
  cam.half_height = scale / (0.92 * zoom);
  return cam;
}

}  // namespace scad::render
