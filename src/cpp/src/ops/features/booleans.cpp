// union_rsolid, cut_rsolid, intersect_rsolid (operators/boolean.py).
#include "scad/ops/features/booleans.hpp"

#include <cmath>
#include <cstdio>
#include <limits>

#include "internal.hpp"
#include "scad/topo/diagnostic_image.hpp"
#include "scad/kernel/booleans.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/ops/features/diagnostics.hpp"
#include "scad/semantic/autotag.hpp"
#include "scad/semantic/tracking.hpp"

namespace scad {

namespace {

constexpr const char* kUnionOp = "make_union_rsolid";
constexpr const char* kCutOp = "make_cut_rsolid";
constexpr const char* kCutListOp = "make_cut_rsolid_list";
constexpr const char* kIntersectOp = "make_intersect_rsolid";

constexpr double kUnionTolFactor = 1e-7;
constexpr double kUnionTolMin = 1e-7;
constexpr double kUnionTolMax = 1e-5;

const ErrorSpec& union_spec() {
  static const ErrorSpec spec{
      "union_rsolid",
      "Failed to compute the boolean union.",
      {"One or more inputs are not Solid objects.", "At least one input solid is null or invalid.",
       "The inputs are separated beyond tol, so the kernel cannot produce exactly one solid.",
       "The inputs meet only along an edge, vertex, tangent point, or tangent curve, so their union is not one "
       "manifold "
       "solid."},
      {"Pass only valid Solid objects or sequences of Solid objects.",
       "For intended face contact, make the solids share a finite-area face and retry; no artificial overlap is "
       "required.",
       "For a real small gap, pass an explicit tol only when approximating that gap is acceptable.",
       "Do not expect glue or tol to turn point-, edge-, or tangent-only contact into a valid single solid."}};
  return spec;
}

const ErrorSpec& cut_spec() {
  static const ErrorSpec spec{
      "cut_rsolid",
      "Failed to compute the boolean cut.",
      {"One or more inputs are not Solid objects.", "The base solid or tool solids are invalid.",
       "The kernel could not compute a valid cut result for the current geometry."},
      {"Pass a valid base solid followed by valid tool solids.",
       "Check whether the tool geometry actually intersects the base solid.",
       "If the cut depends on earlier union results, verify those results first."}};
  return spec;
}

const ErrorSpec& cut_list_spec() {
  static const ErrorSpec spec{
      "cut_rsolid_list",
      "Failed to compute the boolean cut.",
      {"One or more inputs are not Solid objects.", "The base solid or tool solids are invalid.",
       "The kernel could not compute a valid cut result for the current geometry."},
      {"Pass a valid base solid followed by valid tool solids.",
       "Check whether the tool geometry actually intersects the base solid.",
       "If the cut depends on earlier union results, verify those results first."}};
  return spec;
}

const ErrorSpec& intersect_spec() {
  static const ErrorSpec spec{"intersect_rsolid",
                              "Failed to compute the boolean intersection.",
                              {"One or more inputs are not Solid objects.", "At least one input solid is invalid.",
                               "The solids do not overlap enough to produce a non-empty single solid.",
                               "The kernel could not compute a stable overlap region."},
                              {"Pass only valid Solid objects.", "Verify that the solids truly overlap in space.",
                               "Move the solids so they share a meaningful overlap volume before intersecting."}};
  return spec;
}

// _wrap_boolean_failure: the generic guidance, replaced by what re-measuring the operands found.
[[noreturn]] void raise_boolean_failure(const ErrorSpec& base, std::string_view kind, const std::exception& error,
                                        const std::vector<Solid>& operands, std::optional<double> tol, bool diagnose,
                                        std::string what_happened = {}) {
  if (dynamic_cast<const Error*>(&error) != nullptr)
    raise_harness_error(base, error);
  std::optional<BooleanDiagnosis> diagnosis;
  if (diagnose)
    diagnosis = diagnose_boolean_failure(operands, tol, kind);

  ErrorSpec spec = base;
  if (!what_happened.empty())
    spec.what_happened = std::move(what_happened);
  if (diagnosis && !diagnosis->what_happened.empty())
    spec.what_happened = diagnosis->what_happened;
  if (diagnosis && !diagnosis->possible_causes.empty())
    spec.possible_causes = diagnosis->possible_causes;
  std::vector<ErrorEvidence> evidence;
  if (diagnosis && !diagnosis->measurements.empty() && diagnosis->evidence_shapes.size() == 2) {
    // The two operands, told apart by colour; the same unmoved failure is drawn once (agent retry loops).
    DiagnosticImage image;
    image.kind = "render";
    image.operation = base.operation;
    image.view = "default";
    image.caption = diagnosis->evidence_caption;
    char gap[32];
    const auto* first = std::get_if<double>(&diagnosis->measurements.front().value);
    std::snprintf(gap, sizeof gap, "%.1f", first != nullptr ? *first : 0.0);
    image.dedup_key = base.operation + "|" + diagnosis->failure_kind + "|" + gap;
    image.shapes = {diagnosis->evidence_shapes[0], diagnosis->evidence_shapes[1]};
    Value labels = Value::array();
    labels.push_back(Value("operand 1"));
    labels.push_back(Value("operand 2"));
    image.payload.set("operand_labels", std::move(labels));
    if (auto picture = diagnostic_image(image))
      evidence.push_back(std::move(*picture));
  }
  raise_harness_error(spec, error, diagnosis ? diagnosis->measurements : std::vector<ErrorMeasurement>{},
                      diagnosis ? diagnosis->repair : std::vector<std::string>{}, {}, std::move(evidence));
}

bool message_contains(const std::exception& error, std::string_view needle) {
  return std::string_view(error.what()).find(needle) != std::string_view::npos;
}

// _resolve_union_tol: an explicit tolerance must be finite and non-negative (NaN or a negative
// fuzzy value would make kernel failures hard to diagnose); the default scales with the extent.
double resolve_union_tol(const std::vector<Solid>& solids, std::optional<double> tol) {
  if (tol) {
    if (!std::isfinite(*tol) || *tol < 0.0)
      throw ValueError("tol must be a finite non-negative number");
    return *tol;
  }
  constexpr double inf = std::numeric_limits<double>::infinity();
  Vec3 low{inf, inf, inf}, high{-inf, -inf, -inf};
  for (const Solid& solid : solids) {
    const kernel::BoundingBox box = kernel::bounding_box(solid.wrapped());
    low = {std::min(low.x, box.xmin), std::min(low.y, box.ymin), std::min(low.z, box.zmin)};
    high = {std::max(high.x, box.xmax), std::max(high.y, box.ymax), std::max(high.z, box.zmax)};
  }
  const double span = (high - low).norm();
  if (!std::isfinite(span) || span <= 0)
    return kUnionTolMin;
  return std::min(std::max(span * kUnionTolFactor, kUnionTolMin), kUnionTolMax);
}

// _union_separation_diagnostic: the nearest gap beyond `tol` among the pieces a union left apart.
std::optional<std::string> union_separation_diagnostic(const std::vector<TopoDS_Solid>& pieces, double tol) {
  std::optional<double> nearest;
  for (std::size_t i = 0; i < pieces.size(); ++i) {
    for (std::size_t j = i + 1; j < pieces.size(); ++j) {
      const double gap = kernel::distance(pieces[i], pieces[j]);
      if (gap > tol && (!nearest || gap < *nearest))
        nearest = gap;
    }
  }
  if (!nearest)
    return std::nullopt;
  return "union produced " + std::to_string(pieces.size()) + " separated solids; nearest detected gap is about " +
         general_format(*nearest, 6) + ", which exceeds tol=" + general_format(tol, 6);
}

Solid require_union_solid(const TopoDS_Shape& result, double tol) {
  const std::vector<TopoDS_Solid> pieces = kernel::solids_of(result);
  if (pieces.size() == 1)
    return Solid(pieces.front());
  if (const auto diagnostic = union_separation_diagnostic(pieces, tol))
    throw ValueError(*diagnostic);
  if (pieces.size() > 1) {
    throw ValueError("union produced " + std::to_string(pieces.size()) +
                     " solids at zero detected gap; the inputs likely meet only along an edge, vertex, tangent point, "
                     "or tangent curve, which is not one manifold solid");
  }
  throw ValueError("union did not produce a valid solid");
}

std::vector<TopoDS_Shape> wrapped_of(const std::vector<Solid>& solids) {
  std::vector<TopoDS_Shape> out;
  out.reserve(solids.size());
  for (const Solid& solid : solids)
    out.push_back(solid.wrapped());
  return out;
}

void add_operands(FeatureRecord& rec, const std::vector<Solid>& solids) {
  for (std::size_t i = 0; i < solids.size(); ++i)
    rec.input(solids[i], i == 0 ? "body" : "tool");
}

// dict.update: later steps win.
void merge_entries(DeltaEntries& into, DeltaEntries&& from) {
  for (auto& [key, value] : from)
    into.insert_or_assign(key, std::move(value));
}

void require_nonnull(const std::vector<Solid>& solids, const char* message) {
  for (const Solid& solid : solids) {
    if (solid.wrapped().IsNull())
      throw ValueError(message);
  }
}

}  // namespace

void reject_boolean_operand(std::string_view operation) {
  const ErrorSpec* spec = operation == "cut_rsolid"         ? &cut_spec()
                          : operation == "intersect_rsolid" ? &intersect_spec()
                                                            : &union_spec();
  const ValueError cause(std::string(operation) + " only accepts Solid objects");
  raise_harness_error(*spec, cause);
}

// ---------------------------------------------------------------------------
// union
// ---------------------------------------------------------------------------
Solid union_rsolid(const std::vector<Solid>& solids, const UnionOptions& options) {
  std::optional<double> effective_tol;
  try {
    return occt_guard([&]() -> Solid {
      const TrackingPolicy policy = resolve_tracking_policy(options.tracking_policy);
      if (solids.empty())
        throw ValueError("union_rsolid requires at least one Solid input");
      require_nonnull(solids, "The input solid is invalid; the union cannot be computed.");
      if (solids.size() == 1 && !options.clean)
        return solids.front();

      const double tol = resolve_union_tol(solids, options.tol);
      effective_tol = tol;
      const std::vector<TopoDS_Shape> shapes = wrapped_of(solids);

      std::optional<TrackedBooleanResult> tracked;
      Solid fused = [&]() -> Solid {
        if (policy == TrackingPolicy::Full && solids.size() >= 2) {
          const kernel::FuseHistoryResult run =
              kernel::fuse_shapes_with_history(shapes, options.glue, tol, options.clean);
          const Solid result = require_union_solid(run.shape, tol);
          tracked = track_union_history(solids, result, *run.history, run.section_edges);
          if (!tracked->solid)
            throw ValueError("union did not produce a valid solid");
          return *tracked->solid;
        }
        return require_union_solid(kernel::fuse_shapes(shapes, options.glue, tol, options.clean), tol);
      }();
      inherit_metadata(fused, solids);

      FeatureRecord rec(kUnionOp);
      rec.param("input_count", Value(static_cast<std::int64_t>(solids.size())))
          .param("clean", Value(options.clean))
          .param("glue", Value(options.glue))
          .param("tol", Value(tol))
          .param("tracking_policy", Value(std::string(to_string(policy))));
      add_operands(rec, solids);

      FinalizeSpec spec;
      spec.record = std::move(rec).take();
      if (tracked)
        return finalize_tracked_solid(std::move(*tracked), std::move(spec));
      if (policy == TrackingPolicy::Graph)
        return finalize_derived(std::move(fused), std::move(spec));
      return finalize_primitive(std::move(fused), std::move(spec.record));
    });
  } catch (const std::exception& error) {
    const bool separated =
        dynamic_cast<const ValueError*>(&error) != nullptr && message_contains(error, "union produced ");
    raise_boolean_failure(union_spec(), "union", error, solids, effective_tol, /*diagnose=*/true,
                          separated ? std::string(error.what()) : std::string());
  }
}

// ---------------------------------------------------------------------------
// cut
// ---------------------------------------------------------------------------
namespace {

// What a run of cuts left: every piece of the base, and the history of the steps that touched it.
struct CutRun {
  std::vector<Solid> pieces;
  std::vector<TopoDelta> deltas;
  DeltaEntries entries;
  bool cut_performed = false;
  // Every intermediate result stays alive until the merged delta is recorded: step deltas name faces by kernel
  // hashes, which come from the shapes' addresses, and a freed face's address could be reused by an output face.
  std::vector<Solid> intermediates;
};

// The first solid minus every other.  A tool is cut from each piece it meets, and a cut may split a piece in two
// (a slot through a bar), so the answer is a list: empty when the tools consume the base.
CutRun run_cuts(const std::vector<Solid>& solids, const CutOptions& options, TrackingPolicy policy,
                std::string_view operation, bool& no_intersection) {
  if (solids.empty())
    throw ValueError(std::string(operation) + " requires at least one Solid input");
  CutRun run;
  run.pieces.push_back(solids.front());

  for (std::size_t i = 1; i < solids.size(); ++i) {
    const Solid& candidate = solids[i];
    const TopoDS_Shape& s2 = candidate.wrapped();
    if (s2.IsNull())
      throw ValueError("The input solid is invalid; the cut cannot be computed.");

    std::vector<Solid> next;
    bool met = false;  // some piece intersects this tool
    bool too_small = false;
    for (const Solid& piece : run.pieces) {
      const TopoDS_Shape& s1 = piece.wrapped();
      if (s1.IsNull())
        throw ValueError("The input solid is invalid; the cut cannot be computed.");

      const std::vector<TopoDS_Solid> overlap = kernel::solids_of(kernel::common_shapes({s1, s2}));
      if (overlap.empty()) {
        next.push_back(piece);
        continue;
      }
      if (kernel::volume(overlap.front()) < 1e-12) {
        too_small = true;
        next.push_back(piece);
        continue;
      }
      met = true;

      std::vector<Solid> cut_pieces;
      if (policy == TrackingPolicy::Full) {
        TrackedBooleanResult tracked = tracked_cut(piece, candidate);
        cut_pieces = std::move(tracked.solids);
        run.deltas.push_back(std::move(tracked.delta));
        merge_entries(run.entries, std::move(tracked.delta_entries));
      } else {
        for (const TopoDS_Solid& part : kernel::solids_of(kernel::cut_shapes(s1, {s2})))
          cut_pieces.emplace_back(part);
      }
      run.intermediates.push_back(piece);
      for (Solid& part : cut_pieces)
        next.push_back(std::move(part));
      run.cut_performed = true;
    }
    if (!met && !options.skip_non_intersecting) {
      no_intersection = true;
      throw ValueError(too_small ? "The intersection of the cut tool solid and the current solid is too small."
                                 : "The cut tool solid does not intersect the current solid.");
    }
    run.pieces = std::move(next);
  }
  return run;
}

void record_cut(const std::vector<Solid>& solids, const CutOptions& options, TrackingPolicy policy,
                FeatureRecord& rec) {
  rec.param("tool_count", Value(static_cast<std::int64_t>(solids.size() - 1)))
      .param("skip_non_intersecting", Value(options.skip_non_intersecting))
      .param("tracking_policy", Value(std::string(to_string(policy))));
  add_operands(rec, solids);
}

}  // namespace

Solid cut_rsolid(const std::vector<Solid>& solids, const CutOptions& options) {
  bool no_intersection = false;
  try {
    return occt_guard([&]() -> Solid {
      const TrackingPolicy policy = resolve_tracking_policy(options.tracking_policy);
      if (solids.empty())
        throw ValueError("cut_rsolid requires at least one Solid input");
      if (solids.size() == 1)
        return solids.front();

      CutRun run = run_cuts(solids, options, policy, "cut_rsolid", no_intersection);
      if (run.pieces.empty())
        throw ValueError("The cut failed: OCC returned no valid solid");
      if (run.pieces.size() != 1) {
        throw ValueError("cut_rsolid expected a single Solid result but the kernel returned " +
                         std::to_string(run.pieces.size()) +
                         " solids; the cut split the body. Use cut_rsolid_list to keep every piece.");
      }

      Solid result_solid = run.pieces.front();
      inherit_metadata(result_solid, {&solids.front()});
      result_solid.apply_tag("solid.boolean.cut", false);

      std::optional<TopoDelta> merged = merge_topo_deltas(run.deltas);
      FeatureRecord rec(kCutOp);
      record_cut(solids, options, policy, rec);

      FinalizeSpec spec;
      spec.record = std::move(rec).take();
      if (run.cut_performed && merged) {
        return finalize_tracked<Solid>(std::move(result_solid), std::move(*merged), std::move(run.entries),
                                       std::move(spec));
      }
      if (policy == TrackingPolicy::Graph)
        return finalize_derived(std::move(result_solid), std::move(spec));
      return finalize_primitive(std::move(result_solid), std::move(spec.record));
    });
  } catch (const std::exception& error) {
    raise_boolean_failure(cut_spec(), "cut", error, solids, std::nullopt, no_intersection);
  }
}

std::vector<Solid> cut_rsolid_list(const std::vector<Solid>& solids, const CutOptions& options) {
  bool no_intersection = false;
  try {
    return occt_guard([&]() -> std::vector<Solid> {
      const TrackingPolicy policy = resolve_tracking_policy(options.tracking_policy);
      if (solids.empty())
        throw ValueError("cut_rsolid_list requires at least one Solid input");
      if (solids.size() == 1)
        return {solids.front()};

      CutRun run = run_cuts(solids, options, policy, "cut_rsolid_list", no_intersection);

      std::vector<Solid> pieces = std::move(run.pieces);
      std::optional<TopoDelta> merged = merge_topo_deltas(run.deltas);
      const bool tracked = policy != TrackingPolicy::Graph && run.cut_performed && merged;
      std::vector<Shape> sources(solids.begin(), solids.end());
      for (Solid& piece : pieces) {
        inherit_metadata(piece, {&solids.front()});
        piece.apply_tag("solid.boolean.cut", false);
        if (tracked) {
          apply_tracking_tags(piece, *merged, run.entries, TrackingContext{kCutListOp, sources});
        }
        attach_track_summary(piece, kCutListOp, tracked ? &*merged : nullptr, tracked ? &run.entries : nullptr);
      }

      FeatureRecord rec(kCutListOp);
      record_cut(solids, options, policy, rec);
      OpRecord record = std::move(rec).take();
      if (Recorder* recorder = current_recorder()) {
        std::vector<Shape> ordered;
        for (const OpInput& input : record.inputs)
          ordered.push_back(input.shape);
        if (auto refs = recorder->input_refs(ordered))
          record.params.set("input_refs", std::move(*refs));
        if (tracked)
          record.delta = *merged;
      }
      record_operation(std::move(record), std::vector<Shape>(pieces.begin(), pieces.end()));
      return pieces;
    });
  } catch (const std::exception& error) {
    raise_boolean_failure(cut_list_spec(), "cut", error, solids, std::nullopt, no_intersection);
  }
}

// ---------------------------------------------------------------------------
// intersect
// ---------------------------------------------------------------------------
Solid intersect_rsolid(const std::vector<Solid>& solids) {
  bool empty_result = false;
  try {
    return occt_guard([&]() -> Solid {
      if (solids.empty())
        throw ValueError("intersect_rsolid requires at least one Solid input");
      if (solids.size() == 1)
        return solids.front();

      Solid result_solid = solids.front();
      std::vector<TopoDelta> deltas;
      DeltaEntries merged_entries;
      std::vector<Solid> intermediates;  // see cut_rsolid

      for (std::size_t i = 1; i < solids.size(); ++i) {
        const Solid& candidate = solids[i];
        if (result_solid.wrapped().IsNull() || candidate.wrapped().IsNull())
          throw ValueError("The input solid is invalid; the intersection cannot be computed.");
        TrackedBooleanResult tracked = tracked_intersect(result_solid, candidate);
        if (!tracked.solid) {
          empty_result = true;
          throw ValueError("The intersection is empty or OCC returned no valid solid");
        }
        intermediates.push_back(result_solid);
        result_solid = *tracked.solid;
        deltas.push_back(std::move(tracked.delta));
        merge_entries(merged_entries, std::move(tracked.delta_entries));
        if (kernel::volume(result_solid.wrapped()) < 1e-12) {
          empty_result = true;
          throw ValueError("The intersection is empty or its volume is too small");
        }
      }

      inherit_metadata(result_solid, solids);
      result_solid.apply_tag("solid.boolean.intersect", false);

      FeatureRecord rec(kIntersectOp);
      rec.param("input_count", Value(static_cast<std::int64_t>(solids.size())));
      add_operands(rec, solids);
      FinalizeSpec spec;
      spec.record = std::move(rec).take();
      return finalize_tracked<Solid>(std::move(result_solid), std::move(*merge_topo_deltas(deltas)),
                                     std::move(merged_entries), std::move(spec));
    });
  } catch (const std::exception& error) {
    raise_boolean_failure(intersect_spec(), "intersect", error, solids, std::nullopt, empty_result);
  }
}

}  // namespace scad
