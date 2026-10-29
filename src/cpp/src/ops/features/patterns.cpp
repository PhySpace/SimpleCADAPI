// linear_pattern_rsolidlist, radial_pattern_rsolidlist (operators/transform.py).
#include <cmath>

#include "internal.hpp"
#include "scad/ops/features/transforms.hpp"

namespace scad {

namespace {

// Stamp one copy of a pattern: its tag, its position in the pattern, the track summary.
void mark_pattern_member(Shape& member, std::string_view kind, int index, std::string_view op) {
  member.apply_tag("solid.pattern." + std::string(kind), false);
  Value geo = member.get_metadata("geo", Value::object());
  if (!geo.is_object())
    geo = Value::object();
  geo.set("pattern", Value(Value::Object{{"type", Value(std::string(kind))}, {"index", Value(index + 1)}}));
  member.set_metadata("geo", std::move(geo));
  attach_track_summary(member, op);
}

}  // namespace

std::vector<Shape> linear_pattern_rsolidlist(const Shape& shape, const Scalar3& direction, int count,
                                             const Scalar& spacing) {
  static const ErrorSpec spec{
      "linear_pattern_rsolidlist",
      "Failed to create the linear pattern.",
      {"The count is not a positive integer.", "The spacing is not positive.", "The direction vector is invalid."},
      {"Use count >= 1.", "Use spacing > 0.", "Pass a valid finite direction vector."}};
  return guarded(spec, [&]() -> std::vector<Shape> {
    FeatureRecord rec("linear_pattern");
    const double spacing_value = evaluate_finite(spacing);
    if (count <= 0)
      throw ValueError("The pattern count must be greater than zero");
    if (spacing_value <= 0)
      throw ValueError("The pattern spacing must be greater than zero");
    const Vec3 direction_value = evaluate_point(direction, "direction");
    const double norm = direction_value.norm();
    if (norm <= 1e-15 || !std::isfinite(norm))
      throw ValueError("The pattern direction cannot be a zero vector");
    const Vec3 unit = direction_value / norm;

    const bool in_session = recording_session_active();
    std::vector<Shape> copies;
    copies.reserve(static_cast<std::size_t>(count));
    {
      // Outside a session the copies are one recorded operation, not `count` translations.
      std::optional<RecorderSuspend> quiet;
      if (!in_session)
        quiet.emplace();
      for (int i = 0; i < count; ++i)
        copies.push_back(translate_shape(shape, scalar3(unit * (spacing_value * i))));
    }
    for (int i = 0; i < count; ++i)
      mark_pattern_member(copies[static_cast<std::size_t>(i)], "linear", i, "linear_pattern");

    if (!in_session) {
      rec.point("direction", direction);
      rec.param("count", Value(count)).param("spacing", Value(spacing_value));
      record_operation(std::move(rec.input(shape, "shape")).take(), copies);
    }
    return copies;
  });
}

std::vector<Shape> radial_pattern_rsolidlist(const Shape& shape, const Scalar3& center, const Scalar3& axis, int count,
                                             const Scalar& total_rotation_angle) {
  static const ErrorSpec spec{"radial_pattern_rsolidlist",
                              "Failed to create the radial pattern.",
                              {"The count is not a positive integer.", "The total rotation angle is not positive.",
                               "The center or axis is invalid."},
                              {"Use count >= 1.", "Use a total rotation angle greater than zero.",
                               "Pass a valid center point and a non-zero axis vector."}};
  return guarded(spec, [&]() -> std::vector<Shape> {
    const double total = evaluate_finite(total_rotation_angle);
    if (count <= 0)
      throw ValueError("The pattern count must be greater than zero");
    if (total <= 0)
      throw ValueError("The angle must be greater than zero");
    const double step = total / count;

    const bool in_session = recording_session_active();
    std::vector<Shape> copies;
    copies.reserve(static_cast<std::size_t>(count));
    {
      std::optional<RecorderSuspend> quiet;
      if (!in_session)
        quiet.emplace();
      for (int i = 0; i < count; ++i) {
        // A session records every copy; its first is a (zero) move of its own, not the input.
        copies.push_back(in_session && i == 0 ? translate_shape(shape, scalar3(0, 0, 0))
                                              : rotate_shape(shape, Scalar(step * i), axis, center));
      }
    }
    for (int i = 0; i < count; ++i)
      mark_pattern_member(copies[static_cast<std::size_t>(i)], "radial", i, "radial_pattern");

    if (!in_session) {
      FeatureRecord rec("radial_pattern");
      rec.point("center", center);
      rec.point("axis", axis);
      rec.param("count", Value(count)).param("total_rotation_angle", Value(total));
      record_operation(std::move(rec.input(shape, "shape")).take(), copies);
    }
    return copies;
  });
}

}  // namespace scad
