// Port of the fitting tests of test/test_math_helpers.py.
#include "doctest.h"

#include <cmath>
#include <numbers>

#include "scad/core/error.hpp"
#include "scad/reactive/bspline_fit.hpp"

using namespace scad;
using namespace scad::reactive;

namespace {

using Points = std::vector<std::vector<double>>;

double distance(const std::vector<double>& a, const std::vector<double>& b) {
  double sum = 0;
  for (std::size_t i = 0; i < a.size(); ++i)
    sum += (a[i] - b[i]) * (a[i] - b[i]);
  return std::sqrt(sum);
}

Points semicircle() {
  Points samples;
  for (int i = 0; i <= 20; ++i) {
    const double t = i * std::numbers::pi / 20.0;
    samples.push_back({std::cos(t), std::sin(t), 0.0});
  }
  return samples;
}

}  // namespace

TEST_CASE("a line fits with the minimal cubic controls") {
  Points samples;
  for (int i = 0; i < 8; ++i)
    samples.push_back({static_cast<double>(i), 0.0, 0.0});
  const BSplineFit fit = fit_cubic_bspline_control_points(samples, {.tolerance = 1e-10});
  CHECK(fit.converged);
  CHECK(fit.control_count() == 4);
  CHECK(fit.dimension() == 3);
  CHECK(fit.max_error <= 1e-10);
  CHECK(fit.unique_knots() == std::vector<double>{0.0, 1.0});
  CHECK(fit.multiplicities() == std::vector<int>{4, 4});
  CHECK(distance(fit.evaluate(0.0), samples.front()) < 1e-9);
  CHECK(distance(fit.evaluate(1.0), samples.back()) < 1e-9);
  CHECK(distance(fit.evaluate(0.5), {3.5, 0.0, 0.0}) < 1e-9);
}

TEST_CASE("a semicircle adaptively inserts simple knots") {
  const Points samples = semicircle();
  const BSplineFit fit = fit_cubic_bspline_control_points(samples, {.tolerance = 0.002});
  CHECK(fit.converged);
  CHECK(fit.control_count() > 4);
  CHECK(fit.control_count() < samples.size());
  CHECK(fit.max_error <= fit.tolerance);
  const auto multiplicities = fit.multiplicities();
  CHECK(multiplicities.front() == 4);
  CHECK(multiplicities.back() == 4);
  for (std::size_t i = 1; i + 1 < multiplicities.size(); ++i)
    CHECK(multiplicities[i] == 1);
  for (std::size_t i = 0; i < samples.size(); ++i) {
    CHECK(distance(fit.evaluate(fit.sample_parameters[i]), samples[i]) <= fit.tolerance);
  }
}

TEST_CASE("2D samples fit and serialize") {
  const Points samples{{0.0, 0.0}, {0.25, 0.2}, {0.5, -0.1}, {0.75, 0.2}, {1.0, 0.0}};
  const BSplineFit fit = fit_cubic_bspline_control_points(samples, {.tolerance = 0.05, .fairing = 1e-3});
  CHECK(fit.converged);
  CHECK(fit.dimension() == 2);
  const Value payload = fit.to_value();
  CHECK(payload.find("degree")->as_int() == 3);
  CHECK(payload.find("control_points")->size() == fit.control_count());
  CHECK(payload.find("converged")->as_bool());
  CHECK(payload.find("multiplicities")->size() == fit.multiplicities().size());
}

TEST_CASE("consecutive duplicate samples are removed") {
  const Points samples{{0, 0, 0}, {0, 0, 0}, {1, 0, 0}, {2, 0, 0}};
  const BSplineFit fit = fit_cubic_bspline_control_points(samples, {.tolerance = 1e-10});
  CHECK(fit.converged);
  CHECK(fit.sample_parameters.size() == 3);
  CHECK(fit.max_error <= 1e-10);
}

TEST_CASE("the best result is returned when failure is allowed") {
  const BSplineFit fit = fit_cubic_bspline_control_points(
      semicircle(), {.tolerance = 1e-6, .max_control_points = 4, .raise_on_failure = false});
  CHECK_FALSE(fit.converged);
  CHECK(fit.control_count() == 4);
  CHECK(fit.max_error > fit.tolerance);
}

TEST_CASE("an unreachable tolerance raises") {
  try {
    fit_cubic_bspline_control_points(semicircle(), {.tolerance = 1e-6, .max_control_points = 4});
    FAIL("expected a ValueError");
  } catch (const ValueError& e) {
    CHECK(std::string(e.what()).find("failed to fit a cubic B-spline") != std::string::npos);
    CHECK(std::string(e.what()).find("within tolerance 1e-06; best max_error=") != std::string::npos);
  }
}

TEST_CASE("samples and options are validated") {
  const auto message = [](const Points& samples, const BSplineFitOptions& options) {
    try {
      fit_cubic_bspline_control_points(samples, options);
    } catch (const ValueError& e) {
      return std::string(e.what());
    }
    return std::string();
  };
  const Points ok{{0.0, 0.0, 0.0}, {0.5, 0.1, 0.0}, {1.0, 0.0, 0.0}};
  CHECK(message({}, {}) == "sample_points must contain at least two distinct points");
  CHECK(message({{0, 0, 0}, {0, 0, 0}}, {}) == "sample_points must contain at least two distinct points");
  CHECK(message({{0, 0}, {1, 0, 0}}, {}) == "all sample points must have the same dimension");
  CHECK(message({{0}, {1}}, {}) == "sample points must be 2D or 3D");
  CHECK(message({{0, 0}, {std::nan(""), 1}}, {}) == "all sample point coordinates must be finite");
  CHECK(message(ok, {.tolerance = 0.0}).find("tolerance") != std::string::npos);
  CHECK(message(ok, {.fairing = -1.0}).find("fairing") != std::string::npos);
  CHECK(message(ok, {.duplicate_tolerance = -1.0}).find("duplicate_tolerance") != std::string::npos);
  CHECK(message(ok, {.knot_tolerance = 0.0}).find("knot_tolerance") != std::string::npos);
  CHECK(message(ok, {.max_control_points = 3}).find("max_control_points") != std::string::npos);
}

TEST_CASE("two samples give a straight cubic") {
  const BSplineFit fit = fit_cubic_bspline_control_points({{0, 0, 0}, {3, 0, 0}});
  CHECK(fit.converged);
  CHECK(fit.control_count() == 4);
  CHECK(distance(fit.control_points[1], {1, 0, 0}) < 1e-12);
  CHECK(distance(fit.control_points[2], {2, 0, 0}) < 1e-12);
}
