#include <atomic>
#include "scad/std/involute.hpp"

#include <algorithm>
#include <cmath>

#include "scad/reactive/bspline_fit.hpp"

namespace scad::stdlib {

namespace {
std::atomic<std::size_t> g_root_fillet_calls{0};
std::atomic<std::size_t> g_involute_fit_calls{0};
}  // namespace

std::size_t root_fillet_call_count() noexcept {
  return g_root_fillet_calls.load(std::memory_order_relaxed);
}
std::size_t involute_fit_call_count() noexcept {
  return g_involute_fit_calls.load(std::memory_order_relaxed);
}

Point2 involute_point(double base_radius, double t) {
  return {base_radius * (std::cos(t) + t * std::sin(t)), base_radius * (std::sin(t) - t * std::cos(t))};
}

double involute_t_for_radius(double base_radius, double target_radius) {
  const double ratio = target_radius / base_radius;
  return std::sqrt(std::max(ratio * ratio - 1.0, 0.0));
}

Point2 rotate_xy(Point2 p, double angle) {
  const double ca = std::cos(angle);
  const double sa = std::sin(angle);
  return {p.x * ca - p.y * sa, p.x * sa + p.y * ca};
}

BSplineData involute_bspline_control_points(double base_radius, double tip_radius, double start_radius,
                                            double start_angle, bool mirror, bool reverse, int n_segments) {
  const double t_start = involute_t_for_radius(base_radius, start_radius);
  const double t_end = involute_t_for_radius(base_radius, tip_radius);
  const int sample_count = std::max(8, n_segments * 8 + 1);

  std::vector<std::vector<double>> samples;
  samples.reserve(static_cast<std::size_t>(sample_count));
  for (int index = 0; index < sample_count; ++index) {
    const double fraction = static_cast<double>(index) / static_cast<double>(sample_count - 1);
    Point2 point = involute_point(base_radius, t_start + (t_end - t_start) * fraction);
    if (mirror)
      point.y = -point.y;
    point = rotate_xy(point, start_angle);
    samples.push_back({point.x, point.y});
  }
  if (reverse)
    std::reverse(samples.begin(), samples.end());

  reactive::BSplineFitOptions options;
  options.tolerance = 1e-4;
  options.fairing = 1e-8;
  g_involute_fit_calls.fetch_add(1, std::memory_order_relaxed);
  const reactive::BSplineFit fit = reactive::fit_cubic_bspline_control_points(samples, options);

  BSplineData out;
  out.degree = fit.degree;
  out.knots = fit.unique_knots();
  out.multiplicities = fit.multiplicities();
  out.control_points.reserve(fit.control_points.size());
  for (const auto& pole : fit.control_points)
    out.control_points.push_back({pole[0], pole[1]});
  return out;
}

BSplineData root_fillet_control_points(Point2 start, Point2 end, double start_tangent_angle, double end_tangent_angle) {
  g_root_fillet_calls.fetch_add(1, std::memory_order_relaxed);
  const double handle = std::hypot(end.x - start.x, end.y - start.y) * 0.45;
  const Point2 ts{std::cos(start_tangent_angle), std::sin(start_tangent_angle)};
  const Point2 te{std::cos(end_tangent_angle), std::sin(end_tangent_angle)};
  BSplineData out;
  out.control_points = {
      start, {start.x + ts.x * handle, start.y + ts.y * handle}, {end.x - te.x * handle, end.y - te.y * handle}, end};
  out.degree = 3;
  out.knots = {0.0, 1.0};
  out.multiplicities = {4, 4};
  return out;
}

std::vector<Point2> transform_bspline_control_points(const std::vector<Point2>& control_points, double angle,
                                                     bool mirror, bool reverse) {
  std::vector<Point2> out;
  out.reserve(control_points.size());
  for (const Point2& pole : control_points)
    out.push_back(rotate_xy({pole.x, mirror ? -pole.y : pole.y}, angle));
  if (reverse)
    std::reverse(out.begin(), out.end());
  return out;
}

std::pair<std::vector<double>, std::vector<int>> reverse_bspline_parameters(const std::vector<double>& unique_knots,
                                                                            const std::vector<int>& multiplicities) {
  const double parameter_sum = unique_knots.front() + unique_knots.back();
  std::vector<double> knots;
  knots.reserve(unique_knots.size());
  for (auto it = unique_knots.rbegin(); it != unique_knots.rend(); ++it)
    knots.push_back(parameter_sum - *it);
  return {std::move(knots), std::vector<int>(multiplicities.rbegin(), multiplicities.rend())};
}

}  // namespace scad::stdlib
