#include "scad/std/fastener_tables.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>

#include "scad/core/error.hpp"
#include "scad/std/validation.hpp"

namespace scad::stdlib {

namespace {

constexpr std::array<std::pair<double, double>, 34> kMetricCoarsePitch{{
    {1.0, 0.25},  {1.2, 0.25},  {1.4, 0.30},  {1.6, 0.35},  {1.8, 0.35},  {2.0, 0.40},  {2.5, 0.45},
    {3.0, 0.50},  {3.5, 0.60},  {4.0, 0.70},  {5.0, 0.80},  {6.0, 1.00},  {7.0, 1.00},  {8.0, 1.25},
    {10.0, 1.50}, {12.0, 1.75}, {14.0, 2.00}, {16.0, 2.00}, {18.0, 2.50}, {20.0, 2.50}, {22.0, 2.50},
    {24.0, 3.00}, {27.0, 3.00}, {30.0, 3.50}, {33.0, 3.50}, {36.0, 4.00}, {39.0, 4.00}, {42.0, 4.50},
    {45.0, 4.50}, {48.0, 5.00}, {52.0, 5.00}, {56.0, 5.50}, {60.0, 5.50}, {64.0, 6.00},
}};

struct HexHeadRow {
  double diameter, width, height;
};
constexpr std::array<HexHeadRow, 17> kMetricHexHead{{
    {3.0, 5.5, 2.0},
    {4.0, 7.0, 2.8},
    {5.0, 8.0, 3.5},
    {6.0, 10.0, 4.0},
    {8.0, 13.0, 5.3},
    {10.0, 16.0, 6.4},
    {12.0, 18.0, 7.5},
    {14.0, 21.0, 8.8},
    {16.0, 24.0, 10.0},
    {18.0, 27.0, 11.5},
    {20.0, 30.0, 12.5},
    {22.0, 34.0, 14.0},
    {24.0, 36.0, 15.0},
    {27.0, 41.0, 17.0},
    {30.0, 46.0, 18.7},
    {33.0, 50.0, 21.0},
    {36.0, 55.0, 22.5},
}};

// math.isclose(candidate, nominal, rel_tol=0, abs_tol=1e-9)
bool matches_catalog(double candidate, double diameter) {
  return std::fabs(candidate - diameter) <= 1e-9;
}

}  // namespace

std::optional<double> metric_coarse_pitch(double diameter) {
  for (const auto& [nominal, pitch] : kMetricCoarsePitch) {
    if (matches_catalog(nominal, diameter))
      return pitch;
  }
  return std::nullopt;
}

std::optional<HeadDimensions> metric_hex_head_dimensions(double diameter) {
  for (const HexHeadRow& row : kMetricHexHead) {
    if (matches_catalog(row.diameter, diameter))
      return HeadDimensions{row.width, row.height};
  }
  return std::nullopt;
}

ResolvedPitch resolve_thread_pitch(double diameter, const std::optional<double>& thread_pitch) {
  if (thread_pitch)
    return {positive_finite("thread_pitch", *thread_pitch), "explicit"};
  const std::optional<double> pitch = metric_coarse_pitch(diameter);
  if (!pitch)
    throw ValueError("thread_pitch is required when diameter is outside the metric coarse series");
  return {*pitch, "metric_coarse"};
}

std::pair<double, double> metric_thread_dimensions(double diameter, double pitch) {
  const double pitch_diameter = diameter - 0.6495 * pitch;
  const double minor_diameter = diameter - 1.0825 * pitch;
  if (minor_diameter <= 0.0)
    throw ValueError("diameter and thread_pitch produce a non-positive minor diameter");
  return {pitch_diameter, minor_diameter};
}

double standard_partial_thread_length(double diameter, double length) {
  if (length <= 125.0)
    return 2.0 * diameter + 6.0;
  if (length <= 200.0)
    return 2.0 * diameter + 12.0;
  return 2.0 * diameter + 25.0;
}

std::string choice(std::string_view name, std::string_view value, std::initializer_list<std::string_view> choices) {
  std::string lowered(value);
  std::transform(lowered.begin(), lowered.end(), lowered.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (std::find(choices.begin(), choices.end(), lowered) != choices.end())
    return lowered;
  std::string options;
  for (const std::string_view option : choices) {
    if (!options.empty())
      options += ", ";
    options += option;
  }
  throw ValueError(std::string(name) + " must be one of: " + options);
}

}  // namespace scad::stdlib
