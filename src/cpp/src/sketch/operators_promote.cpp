// inspect_sketch_rsketchresult, make_wire_from_sketch_rwire, make_face_from_sketch_rface.
#include <TopoDS.hxx>

#include "finalize.hpp"
#include "promotion.hpp"
#include "scad/core/error.hpp"
#include "scad/kernel/features.hpp"
#include "scad/sketch/operators.hpp"

namespace scad {

namespace {

using namespace sketch_detail;  // NOLINT(google-build-using-namespace): file-local glue

Value solve_params(const SketchSolveRequest& request) {
  Value params = Value::object();
  params.set("require_fully_constrained", request.require_fully_constrained);
  params.set("strict", request.strict);
  params.set("tolerance", request.tolerance);
  params.set("max_iterations", request.max_iterations);
  return params;
}

// Params shared by both promotions, in the Python order.
Value promotion_params(const Sketch& sketch, const SketchProfileId& profile, const SketchSolveRequest& request,
                       const Promotion& promotion, const char* target_kind, const Value* inner_profiles) {
  Value params = Value::object();
  params.set("profile", profile.to_value());
  if (inner_profiles != nullptr)
    params.set("inner_profiles", *inner_profiles);
  params.set("sketch", sketch.to_value());
  const Value solve = solve_params(request);
  for (const auto& [key, value] : solve.as_object())
    params.set(key, value);
  params.set("solve_snapshot", promotion.solve_result.to_value());
  params.set("promotion_map",
             sketch_promotion_map(sketch, profile, promotion.profile_payload, promotion.inner_profiles, target_kind));
  return params;
}

}  // namespace

SketchSolveResult inspect_sketch_rsketchresult(const Sketch& sketch, const SketchSolveRequest& request) {
  static const ErrorSpec kSpec{"inspect_sketch_rsketchresult",
                               "Failed to inspect the sketch constraints.",
                               {"The sketch has invalid, conflicting, or underconstrained constraints.",
                                "A constraint references a missing or wrong-kind entity."},
                               {"Inspect diagnostics with strict=False if needed.",
                                "Add fix/dimension constraints until the intended profile is fully constrained."}};
  return guarded(kSpec, [&] {
    Sketch working = sketch.clone(/*include_solve=*/false);
    return working.solve(request);
  });
}

Wire make_wire_from_sketch_rwire(const Sketch& sketch, const SketchProfileId& profile,
                                 const SketchSolveRequest& request) {
  static const ErrorSpec kSpec{
      "make_wire_from_sketch_rwire",
      "Failed to create a wire from the sketch.",
      {"The sketch has no promotable component: every non-construction edge set must be a closed loop, an open "
       "chain, or a circle.",
       "An edge set branches at a point carrying more than two edges.",
       "The sketch constraints are conflicting or invalid.", "The requested profile index or id does not exist."},
      {"Build sketch paths only through sketch APIs; connect entities by sharing point ids and avoid branch points "
       "with three or more edges.",
       "Closedness is not required here \xE2\x80\x94 extrude and face consumers enforce it on the resulting wire.",
       "Call inspect_sketch_rsketchresult(..., strict=False) to inspect diagnostics."}};
  return guarded(kSpec, [&] {
    return occt_guard([&] {
      Promotion promotion = promote_sketch_profile(sketch, profile, PromotionTarget::Wire, {}, request);
      Value params = promotion_params(sketch, profile, request, promotion, "wire", nullptr);
      Shape shape =
          finalize_sketch_promotion(promotion.shape, "make_wire_from_sketch_rwire", std::move(params), sketch);
      apply_sketch_promotion_identity_tags(shape, sketch, promotion, "make_wire_from_sketch_rwire");
      return Wire(shape);
    });
  });
}

Face make_face_from_sketch_rface(const Sketch& sketch, const SketchProfileId& profile,
                                 const std::vector<SketchProfileId>& inner_profiles,
                                 const SketchSolveRequest& request) {
  static const ErrorSpec kSpec{
      "make_face_from_sketch_rface",
      "Failed to create a face from the sketch.",
      {"The sketch has no closed profile; faces require closed loops (open chains are wire-only \xE2\x80\x94 promote "
       "them with make_wire_from_sketch_rwire instead).",
       "The sketch constraints are conflicting or invalid.", "The requested profile index or id does not exist.",
       "An inner profile is outside, intersects, or duplicates the outer profile."},
      {"Build closed profiles with add_line_rsketch(...) or add_circle_rsketch(...).",
       "Add constraints until the profile can solve cleanly.",
       "Pass hole loops explicitly with inner_profiles=[...]."}};
  return guarded(kSpec, [&] {
    return occt_guard([&] {
      Promotion promotion = promote_sketch_profile(sketch, profile, PromotionTarget::Face, inner_profiles, request);
      Value::Array inner_values;
      for (const SketchProfileId& inner : inner_profiles)
        inner_values.push_back(inner.to_value());
      const Value inner_value(std::move(inner_values));
      Value params = promotion_params(sketch, profile, request, promotion, "face", &inner_value);
      Shape shape =
          finalize_sketch_promotion(promotion.shape, "make_face_from_sketch_rface", std::move(params), sketch);
      apply_sketch_promotion_identity_tags(shape, sketch, promotion, "make_face_from_sketch_rface");
      return Face(shape);
    });
  });
}

std::vector<Face> sketch_to_faces(const Sketch& sketch) {
  if (!sketch.entities().empty())
    return {make_face_from_sketch_rface(sketch)};
  std::vector<Face> faces;
  for (const Wire& wire : sketch.closed_wires()) {
    faces.emplace_back(kernel::make_face_from_wire(TopoDS::Wire(wire.wrapped())));
  }
  return faces;
}

}  // namespace scad
