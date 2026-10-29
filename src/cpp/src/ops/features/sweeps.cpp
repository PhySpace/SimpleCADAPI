// loft_rsolid, sweep_rsolid, twisted_sweep_rsolid (operators/features.py).
#include "scad/ops/features/sweeps.hpp"

#include <algorithm>
#include <cmath>

#include "internal.hpp"
#include "scad/ops/features/diagnostics.hpp"
#include "scad/semantic/tracking.hpp"

namespace scad {

namespace {

constexpr const char* kLoftOp = "make_loft_rsolid";
constexpr const char* kSweepOp = "make_sweep_rsolid";
constexpr const char* kTwistedOp = "make_twisted_sweep_rsolid";

// _validated_loft_sections
void validate_loft_sections(const std::vector<Shape>& sections, std::string_view operation) {
  const std::string name(operation);
  if (sections.size() < 2)
    throw ValueError(name + " requires at least two sections");
  for (const Shape& section : sections) {
    if (section.kind() != Kind::Wire && section.kind() != Kind::Vertex) {
      throw TypeError(name + " sections must contain only Wire or Vertex objects");
    }
  }
  const auto is_wire = [](const Shape& s) { return s.kind() == Kind::Wire; };
  if (std::none_of(sections.begin(), sections.end(), is_wire))
    throw ValueError(name + " requires at least one Wire section");
  for (std::size_t i = 1; i + 1 < sections.size(); ++i) {
    if (sections[i].kind() == Kind::Vertex)
      throw ValueError(name + " allows Vertex sections only at the start or end");
  }
}

}  // namespace

Solid loft_rsolid(const std::vector<Shape>& profiles, bool ruled, const LoftOptions& options) {
  static const ErrorSpec spec{
      "loft_rsolid",
      "Failed to loft the input profiles into a solid.",
      {"Fewer than two sections were provided.", "A Vertex section was used away from the start or end.",
       "One or more Wire/Vertex sections are invalid or incompatible.",
       "The kernel rejected the loft because the section geometry is inconsistent."},
      {"Pass at least two Wire or endpoint Vertex sections.", "Keep Wire topology compatible across sections.",
       "If loft fails, inspect each section individually and simplify its geometry."}};
  try {
    return occt_guard([&]() -> Solid {
      validate_loft_sections(profiles, "loft_rsolid");
      const SweepTags& tags = options.tags;
      if (tags.start_face_tag && profiles.front().kind() == Kind::Vertex)
        throw ValueError("start_face_tag requires a Wire start section");
      if (tags.end_face_tag && profiles.back().kind() == Kind::Vertex)
        throw ValueError("end_face_tag requires a Wire end section");
      const TrackingPolicy policy = resolve_tracking_policy(options.tracking_policy);
      const OutputTags output = features_detail::sweep_output_tags(tags, "loft.start", "loft.end", "loft.side");
      const OutputTagPlan plan = plan_output_tags(kLoftOp, output);
      if (policy == TrackingPolicy::Graph && (!plan.assignments.empty() || tags.tag_prefix)) {
        throw ValueError(
            "GRAPH tracking does not provide loft face-role evidence; use FULL tracking for tag_prefix, "
            "start_face_tag, end_face_tag, or side_faces_tag");
      }

      FeatureRecord rec(kLoftOp);
      rec.param("profile_count", Value(static_cast<std::int64_t>(profiles.size())))
          .param("ruled", Value(ruled))
          .param("tracking_policy", Value(std::string(to_string(policy))))
          .inputs(profiles, "profile");

      FinalizeSpec finalize;
      finalize.tags = output;
      if (policy == TrackingPolicy::Full) {
        TrackedResult tracked = tracked_loft(profiles, ruled);
        inherit_metadata(tracked.shape, profiles);
        finalize.record = std::move(rec).take();
        finalize.roles.start = profiles.front().kind() == Kind::Wire ? "loft.start" : "";
        finalize.roles.end = profiles.back().kind() == Kind::Wire ? "loft.end" : "";
        finalize.roles.side = "loft.side";
        return finalize_tracked_solid(std::move(tracked), std::move(finalize));
      }
      std::vector<TopoDS_Shape> sections;
      for (const Shape& profile : profiles)
        sections.push_back(profile.wrapped());
      Solid result(kernel::make_loft_solid(sections, ruled));
      inherit_metadata(result, profiles);
      finalize.record = std::move(rec).take();
      return finalize_derived(std::move(result), std::move(finalize));
    });
  } catch (const std::exception& error) {
    if (dynamic_cast<const Error*>(&error) == nullptr)
      raise_loft_failure_if_diagnosed(profiles, "loft_rsolid");
    raise_harness_error(spec, error);
  }
}

Solid sweep_rsolid(const Face& profile, const Wire& path, bool is_frenet, const SweepTags& tags) {
  static const ErrorSpec spec{"sweep_rsolid",
                              "Failed to sweep the profile along the path.",
                              {"The profile face is invalid.", "The path wire is invalid or unsuitable for sweep.",
                               "The kernel rejected the sweep orientation or geometry."},
                              {"Pass a valid Face profile and a valid Wire path.",
                               "Check that the path wire is continuous and geometrically reasonable.",
                               "If sweep fails, simplify the profile or path before retrying."}};
  return guarded(spec, [&]() -> Solid {
    const OutputTags output = features_detail::sweep_output_tags(tags, "sweep.start", "sweep.end", "sweep.side");
    plan_output_tags(kSweepOp, output);

    TrackedResult tracked = tracked_sweep(profile, path, is_frenet);
    inherit_metadata(tracked.shape, {&profile, &path});

    FeatureRecord rec(kSweepOp);
    rec.param("is_frenet", Value(is_frenet)).input(profile, "profile").input(path, "path");
    FinalizeSpec finalize;
    finalize.record = std::move(rec).take();
    finalize.tags = output;
    finalize.roles.start = "sweep.start";
    finalize.roles.end = "sweep.end";
    finalize.roles.side = "sweep.side";
    return finalize_tracked_solid(std::move(tracked), std::move(finalize));
  });
}

Solid twisted_sweep_rsolid(const Shape& profile, const Scalar& distance, const Scalar& twist_angle, const Scalar3& axis,
                           const Scalar3& origin, const TwistedSweepOptions& options) {
  static const ErrorSpec spec{"twisted_sweep_rsolid",
                              "Failed to sweep the profile with a linear axial rotation.",
                              {"The profile is invalid or contains inner wires.",
                               "The distance, twist angle, axis, or guide radius is invalid.",
                               "The requested twist causes self-intersection or kernel failure."},
                              {"Pass a valid planar Face without inner wires.",
                               "Use a positive distance and guide radius with a non-zero axis.",
                               "Reduce the twist angle or simplify the profile."}};
  return guarded(spec, [&]() -> Solid {
    if (profile.kind() != Kind::Face)
      throw TypeError("profile must be a Face");
    FeatureRecord rec(kTwistedOp);
    const double distance_value = rec.scalar("distance", distance);
    const double twist_value = rec.scalar("twist_angle", twist_angle);
    const double guide_radius = rec.scalar("guide_radius", options.guide_radius);
    if (!std::isfinite(distance_value) || distance_value <= 0.0)
      throw ValueError("distance must be a finite positive number");
    if (!std::isfinite(twist_value))
      throw ValueError("twist_angle must be finite");
    if (!std::isfinite(guide_radius) || guide_radius <= 0.0)
      throw ValueError("guide_radius must be a finite positive number");

    const Vec3 global_axis = features_detail::place_vector(rec.point("axis", axis));
    const Vec3 global_origin = features_detail::place_point(rec.point("origin", origin));
    const double axis_norm = global_axis.norm();
    if (!std::isfinite(axis_norm) || axis_norm <= 1.0e-15)
      throw ValueError("axis must be a finite non-zero vector");

    const OutputTags output = features_detail::sweep_output_tags(options.tags, "twisted_sweep.start",
                                                                 "twisted_sweep.end", "twisted_sweep.side");
    plan_output_tags(kTwistedOp, output);

    TrackedResult tracked = tracked_twisted_sweep(Face(profile), global_axis / axis_norm, global_origin, distance_value,
                                                  twist_value, guide_radius);
    // The kernel's approximation report survives the metadata inherited from the profile.
    const Value kernel_metadata = tracked.shape.get_metadata("twisted_sweep.kernel", Value::object());
    inherit_metadata(tracked.shape, {&profile});
    tracked.shape.set_metadata("twisted_sweep.kernel", kernel_metadata);

    FinalizeSpec finalize;
    finalize.record = std::move(rec.input(profile, "profile")).take();
    finalize.tags = output;
    finalize.roles.start = "twisted_sweep.start";
    finalize.roles.end = "twisted_sweep.end";
    finalize.roles.side = "twisted_sweep.side";
    return finalize_tracked_solid(std::move(tracked), std::move(finalize));
  });
}

}  // namespace scad
