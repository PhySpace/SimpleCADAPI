// The standard sizes and thread arithmetic behind the bolt and nut factories.
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <utility>

namespace scad::stdlib {

// ISO metric coarse pitch of a catalog nominal diameter (1 .. 64 mm); nullopt for any other size.
// Diameters match a catalog entry within 1e-9 mm.
std::optional<double> metric_coarse_pitch(double diameter);

// ISO 4014/4017 hex-head across-flats width `s` and head height `k` (3 .. 36 mm).
struct HeadDimensions {
  double width = 0.0;
  double height = 0.0;
};
std::optional<HeadDimensions> metric_hex_head_dimensions(double diameter);

// Where a thread pitch came from: "explicit" or "metric_coarse".
struct ResolvedPitch {
  double pitch = 0.0;
  std::string source;
};
// ValueError when `thread_pitch` is absent and `diameter` is outside the coarse series.
ResolvedPitch resolve_thread_pitch(double diameter, const std::optional<double>& thread_pitch);

// Pitch and minor diameter of a metric thread (0.6495 p and 1.0825 p below the major diameter).
// ValueError when the minor diameter is not positive.
std::pair<double, double> metric_thread_dimensions(double diameter, double pitch);

// The unthreaded-shank rule of ISO 4014: 2d + 6 up to 125 mm, 2d + 12 up to 200 mm, else 2d + 25.
double standard_partial_thread_length(double diameter, double length);

// `value` lower-cased, which must be one of `choices` (sorted); ValueError "<name> must be one of: ...".
std::string choice(std::string_view name, std::string_view value, std::initializer_list<std::string_view> choices);

}  // namespace scad::stdlib
