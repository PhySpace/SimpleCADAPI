// fillet_rsolid, chamfer_rsolid (operators/features.py).
#include "scad/ops/features/blends.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <functional>

#include "internal.hpp"
#include "scad/ops/features/diagnostics.hpp"
#include "scad/topo/diagnostic_image.hpp"
#include "scad/semantic/tracking.hpp"

namespace scad {

namespace {

constexpr const char* kFilletOp = "make_fillet_rsolid";
constexpr const char* kChamferOp = "make_chamfer_rsolid";

// What the failure handler knows about the attempt, as far as it got.
struct BlendAttempt {
  std::vector<Edge> edges;
  std::optional<double> size;
};

// _wrap_blend_failure: the generic guidance, replaced by what the probes found
// out about this particular solid.  Never returns.
[[noreturn]] void raise_blend_failure(const ErrorSpec& base, const std::exception& error, const Solid& solid,
                                      const BlendAttempt& attempt, std::string_view kind, const BlendRetry& retry) {
  if (dynamic_cast<const Error*>(&error) != nullptr)
    raise_harness_error(base, error);

  // When the exit check caught impossible output its measured volumes lead
  // what_happened: "the kernel refused" and "the kernel silently lied" are
  // different failures.
  const auto* violation = dynamic_cast<const BlendVolumeViolation*>(&error);
  std::optional<BlendDiagnosis> diagnosis;
  if (attempt.size && !attempt.edges.empty())
    diagnosis = diagnose_blend_failure(solid, attempt.edges, *attempt.size, kind, retry);

  ErrorSpec spec = base;
  const bool explained = diagnosis && !diagnosis->what_happened.empty();
  if (explained)
    spec.what_happened = diagnosis->what_happened;
  if (violation != nullptr) {
    spec.what_happened = explained ? std::string(violation->what()) + "; probes indicate: " + spec.what_happened
                                   : std::string(violation->what());
  }
  if (diagnosis && !diagnosis->possible_causes.empty())
    spec.possible_causes = diagnosis->possible_causes;

  const std::string details =
      violation != nullptr ? "BlendVolumeViolation: " + std::string(violation->what()) : technical_details_of(error);
  std::vector<ErrorEvidence> evidence;
  if (diagnosis && !diagnosis->evidence_edges.empty()) {
    // The solid with the implicated edges in orange; the same failure at the same size is drawn once per process
    // (agent retry loops must not pay again).
    DiagnosticImage image;
    image.kind = "render";
    image.operation = base.operation;
    image.view = "default";
    image.caption = diagnosis->evidence_caption;
    char size[32];
    std::snprintf(size, sizeof size, "%.1f", *attempt.size);
    image.dedup_key = diagnosis->failure_kind + "|" + size;
    image.shapes.push_back(solid);
    for (const Edge& edge : diagnosis->evidence_edges)
      image.shapes.push_back(edge);
    image.payload.set("mode", Value("highlight_edges"));
    image.payload.set("edge_count", Value(static_cast<std::int64_t>(diagnosis->evidence_edges.size())));
    if (auto picture = diagnostic_image(image))
      evidence.push_back(std::move(*picture));
  }
  raise_harness_error(spec, details, diagnosis ? diagnosis->measurements : std::vector<ErrorMeasurement>{},
                      diagnosis ? diagnosis->repair : std::vector<std::string>{}, {}, std::move(evidence));
}

// The shared flow of fillet and chamfer once the size and the edges are known.
// `between` records the params the operator puts between the references and the
// node ids.
Solid finish_blend(const Solid& solid, TrackedResult tracked, const BlendAttempt& attempt, std::string_view kind,
                   double check_size, FeatureRecord& rec, const BlendTags& tags, std::string_view patch_role,
                   const std::function<void()>& between = {}) {
  assert_blend_volume_monotonic(solid, Solid(tracked.shape), kind, check_size, attempt.edges);
  inherit_metadata(tracked.shape, {&solid});

  rec.param("edge_count", Value(static_cast<std::int64_t>(attempt.edges.size())));
  PickParams picks;
  if (rec.recording())
    picks = capture_picks(solid, attempt.edges, solid.edges(), /*refs_first=*/true);
  if (rec.recording()) {
    picks.apply_refs(rec, "selected_edges");
    if (between)
      between();
    picks.apply_ids(rec, "selected_edge_node_ids", "selected_edge_indices");
  }
  rec.input(solid, "body").inputs(attempt.edges, "edge");

  FinalizeSpec spec;
  spec.record = std::move(rec).take();
  spec.tags.result_tag = tags.result_tag;
  spec.tags.roles = {{std::string(patch_role), tags.generated_faces_tag}};
  return finalize_tracked_solid(std::move(tracked), std::move(spec));
}

}  // namespace

Solid fillet_rsolid(const Solid& solid, const EdgeSelection& edges, const Scalar& radius, const BlendTags& tags) {
  static const ErrorSpec spec{"fillet_rsolid",
                              "Failed to apply the fillet operation.",
                              {"The radius is not a positive finite scalar.", "No valid edges were selected.",
                               "The selected edges are incompatible with the requested fillet radius."},
                              {"Use a positive fillet radius.",
                               "Select at least one valid edge or use a selector that resolves to "
                               "edges.",
                               "If the kernel rejects the fillet, try a smaller radius or a simpler "
                               "edge set."}};
  BlendAttempt attempt;
  try {
    return occt_guard([&]() -> Solid {
      OutputTags output;
      output.result_tag = tags.result_tag;
      output.roles = {{"fillet.patch", tags.generated_faces_tag}};
      plan_output_tags(kFilletOp, output);

      FeatureRecord rec(kFilletOp);
      const double radius_value = rec.scalar("radius", radius);
      attempt.size = radius_value;
      if (radius_value <= 0)
        throw ValueError("The radius of fillet must be large than 0");
      attempt.edges = edges.resolve(solid);
      if (attempt.edges.empty())
        throw ValueError("At least one edge should be selected as the target for fillet");

      TrackedResult tracked = tracked_fillet(solid, attempt.edges, radius_value);
      return finish_blend(solid, std::move(tracked), attempt, "fillet", radius_value, rec, tags, "fillet.patch");
    });
  } catch (const std::exception& error) {
    const BlendRetry retry = [&](const Edge& edge) {
      try {
        (void)tracked_fillet(solid, {edge}, *attempt.size);
        return true;
      } catch (const std::exception&) {
        return false;
      }
    };
    raise_blend_failure(spec, error, solid, attempt, "fillet", attempt.size ? retry : BlendRetry{});
  }
}

namespace {

// _chamfer_reference_face_pairs: each edge's two faces ordered (reference,
// other), the reference being the face whose outward normal best matches
// `reference_direction`.
std::vector<std::pair<Face, Face>> chamfer_reference_face_pairs(const std::vector<Edge>& edges,
                                                                const Vec3& reference_direction) {
  const double norm = reference_direction.norm();
  if (norm <= 1e-12)
    throw ValueError("chamfer reference_direction must be non-zero");
  const Vec3 direction = reference_direction / norm;
  std::vector<std::pair<Face, Face>> pairs;
  pairs.reserve(edges.size());
  for (const Edge& edge : edges) {
    std::vector<Face> faces = edge.incident_faces();
    if (faces.size() < 2)
      throw ValueError("An angled chamfer needs two adjacent faces per selected edge");
    std::vector<std::pair<double, Face>> ranked;
    for (const Face& face : faces)
      ranked.emplace_back(face.normal_at().dot(direction), face);
    std::stable_sort(ranked.begin(), ranked.end(), [](const auto& a, const auto& b) { return a.first > b.first; });
    pairs.emplace_back(ranked[0].second, ranked[1].second);
  }
  return pairs;
}

Value vec_value(const Vec3& v) {
  return Value::tuple({Value(v.x), Value(v.y), Value(v.z)});
}

}  // namespace

Solid chamfer_rsolid(const Solid& solid, const EdgeSelection& edges, const Scalar& distance,
                     const ChamferOptions& options) {
  static const ErrorSpec spec{"chamfer_rsolid",
                              "Failed to apply the chamfer operation.",
                              {"The distance is not a positive finite scalar.", "No valid edges were selected.",
                               "The selected edges are incompatible with the requested chamfer size."},
                              {"Use a positive chamfer distance.",
                               "Select at least one valid edge or use a selector that resolves to "
                               "edges.",
                               "If the kernel rejects the chamfer, try a smaller distance or fewer "
                               "edges."}};
  BlendAttempt attempt;
  std::optional<double> distance_value, distance2;
  try {
    return occt_guard([&]() -> Solid {
      OutputTags output;
      output.result_tag = options.tags.result_tag;
      output.roles = {{"chamfer.patch", options.tags.generated_faces_tag}};
      plan_output_tags(kChamferOp, output);

      FeatureRecord rec(kChamferOp);
      distance_value = rec.scalar("distance", distance);
      if (*distance_value <= 0)
        throw ValueError("The chamfer distance must be greater than zero");
      attempt.size = distance_value;
      attempt.edges = edges.resolve(solid);
      if (attempt.edges.empty())
        throw ValueError("At least one edge should be selected as the target for chamfer");

      std::vector<std::pair<Face, Face>> face_pairs;
      if (options.angle) {
        if (!options.reference_direction) {
          throw ValueError(
              "An angled chamfer requires reference_direction to "
              "pick the face anchoring the distance");
        }
        const double radians = *options.angle * kPi / 180.0;
        if (!(0.0 < radians && radians < 0.5 * kPi))
          throw ValueError("Chamfer angle must be between 0 and 90 degrees");
        distance2 = *distance_value * std::tan(radians);
        face_pairs = chamfer_reference_face_pairs(attempt.edges, *options.reference_direction);
      }

      TrackedResult tracked = tracked_chamfer(solid, attempt.edges, *distance_value, distance2, face_pairs);
      // The effective size of an angled chamfer spans both legs.
      const double check_size = distance2 ? std::max(*distance_value, *distance2) : *distance_value;
      attempt.size = check_size;
      return finish_blend(solid, std::move(tracked), attempt, "chamfer", check_size, rec, options.tags, "chamfer.patch",
                          [&] {
                            rec.param("angle", options.angle ? Value(*options.angle) : Value());
                            rec.param("reference_direction",
                                      options.reference_direction ? vec_value(*options.reference_direction) : Value());
                            if (distance2)
                              rec.param("distance2", Value(*distance2));
                          });
    });
  } catch (const std::exception& error) {
    if (distance_value)
      attempt.size = std::max(*distance_value, distance2.value_or(0.0));
    const BlendRetry retry = [&](const Edge& edge) {
      try {
        (void)tracked_chamfer(solid, {edge}, *distance_value, distance2);
        return true;
      } catch (const std::exception&) {
        return false;
      }
    };
    raise_blend_failure(spec, error, solid, attempt, "chamfer", distance_value ? retry : BlendRetry{});
  }
}

Solid shell_rsolid(const Solid& solid, const FaceSelection& faces_to_remove, const Scalar& thickness,
                   const ShellTags& tags) {
  static const ErrorSpec spec{
      "shell_rsolid",
      "Failed to apply the shell operation.",
      {"The thickness is not a positive finite scalar.", "No valid faces were selected for removal.",
       "The requested shell thickness is incompatible with the current solid."},
      {"Use a positive shell thickness.", "Select at least one valid face to remove.",
       "If the shell fails, try a smaller thickness or a different face "
       "selection."}};
  return guarded(spec, [&]() -> Solid {
    constexpr const char* kShellOp = "make_shell_rsolid";
    OutputTags output;
    output.result_tag = tags.result_tag;
    output.roles = {{"shell.body_face", tags.body_faces_tag},
                    {"shell.offset_face", tags.offset_faces_tag},
                    {"shell.closing_descendant", tags.closing_faces_tag},
                    {"shell.wall", tags.wall_edges_tag}};
    plan_output_tags(kShellOp, output);

    FeatureRecord rec(kShellOp);
    const double thickness_value = rec.scalar("thickness", thickness);
    if (thickness_value <= 0)
      throw ValueError("The shell thickness must be greater than zero");
    const std::vector<Face> removed = faces_to_remove.resolve(solid);
    if (removed.empty())
      throw ValueError("At least one face should be selected for removal in the shell operation");

    TrackedResult tracked = tracked_shell(solid, removed, thickness_value);
    inherit_metadata(tracked.shape, {&solid});
    rec.param("removed_face_count", Value(static_cast<std::int64_t>(removed.size())));
    if (rec.recording()) {
      const PickParams picks = capture_picks(solid, removed, solid.faces(), /*refs_first=*/true);
      picks.apply_refs(rec, "selected_faces");
      picks.apply_ids(rec, "selected_face_node_ids", "selected_face_indices");
    }
    rec.input(solid, "body").inputs(removed, "face");

    FinalizeSpec finalize;
    finalize.record = std::move(rec).take();
    finalize.tags = output;
    return finalize_tracked_solid(std::move(tracked), std::move(finalize));
  });
}

}  // namespace scad
