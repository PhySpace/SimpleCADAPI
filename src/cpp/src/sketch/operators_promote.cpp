// inspect_sketch_rsketchresult, inspect_sketch_rsketchprofiles, make_wire_from_sketch_rwire,
// make_face_from_sketch_rface.
#include <TopoDS.hxx>

#include "finalize.hpp"
#include "promotion.hpp"
#include "regions.hpp"
#include "scad/core/error.hpp"
#include "scad/kernel/features.hpp"
#include "scad/sketch/operators.hpp"
#include "scad/sketch/profile.hpp"

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

Value inspect_sketch_rsketchprofiles(const Sketch& sketch, const SketchSolveRequest& request) {
  static const ErrorSpec kSpec{"inspect_sketch_rsketchprofiles",
                               "Failed to list the sketch profiles.",
                               {"The sketch has invalid or conflicting constraints and strict=True."},
                               {"Pass strict=False to list the profiles of a sketch that does not solve cleanly."}};
  return guarded(kSpec, [&] {
    Sketch working = sketch.clone(/*include_solve=*/false);
    const SketchSolveResult result = working.solve(request);
    const auto strings = [](const std::vector<std::string>& ids) {
      Value::Array out;
      for (const std::string& id : ids)
        out.emplace_back(id);
      return Value(std::move(out));
    };
    Value::Array profiles;
    Value::Array components;
    Value::Array regions;
    if (!result.solved_points.empty()) {
      const std::vector<SketchProfile> listed = sketch_profiles(working, result);
      std::vector<ProfileNesting> nesting(listed.size());
      try {
        nesting = profile_nesting(working, result, listed);
      } catch (const std::exception&) {  // geometry the solve left unusable: no nesting, the profiles still list
      }
      const auto number_or_null = [](int value) { return value < 0 ? Value() : Value(value); };
      int index = 0;
      for (const SketchProfile& profile : listed) {
        const ProfileNesting& nest = nesting[static_cast<std::size_t>(index)];
        if (profile.closed && nest.depth >= 0 && nest.depth % 2 == 0) {
          Value region = Value::object();
          region.set("outer", index);
          Value::Array holes;
          for (std::size_t j = 0; j < listed.size(); ++j)
            if (nesting[j].parent == index)
              holes.emplace_back(static_cast<int>(j));
          region.set("holes", Value(std::move(holes)));
          regions.push_back(std::move(region));
        }
        Value item = Value::object();
        item.set("parent", number_or_null(nest.parent));
        item.set("depth", number_or_null(nest.depth));
        item.set("index", index++);
        item.set("id", profile.id);
        item.set("kind", profile.kind);
        item.set("closed", profile.closed);
        item.set("entity_ids", strings(profile.entity_ids));
        item.set("point_ids", strings(profile.point_ids));
        Value::Array reversed;
        for (const bool flag : profile.reversed)
          reversed.emplace_back(flag);
        item.set("reversed", Value(std::move(reversed)));
        profiles.push_back(std::move(item));
      }
      for (const std::string& text : describe_edge_components(working)) {
        if (text.rfind("closed loop", 0) != 0 && text.rfind("open chain", 0) != 0)
          components.emplace_back(text);
      }
    }
    Value out = Value::object();
    out.set("profiles", Value(std::move(profiles)));
    out.set("unusable", Value(std::move(components)));
    out.set("regions", Value(std::move(regions)));
    return out;
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

std::vector<Face> make_faces_from_sketch_rfacelist(const Sketch& sketch,
                                                   const std::optional<std::vector<SketchProfileId>>& profiles,
                                                   const SketchSolveRequest& request) {
  static const ErrorSpec kSpec{
      "make_faces_from_sketch_rfacelist",
      "Failed to create the faces of the sketch's regions.",
      {"The sketch has no closed profile.",
       "A requested profile does not exist, is an open chain, or is a hole "
       "(a loop inside another loop).",
       "The sketch constraints are conflicting or invalid."},
      {"List the regions with inspect_sketch_rsketchprofiles(...)['regions'] and pass their outer profiles.",
       "Leave profiles out to make every region.", "Add constraints until the profile can solve cleanly."}};
  return guarded(kSpec, [&] {
    Sketch working = sketch.clone(/*include_solve=*/false);
    const SketchSolveResult result = working.solve(request);
    const std::vector<SketchProfile> listed = sketch_profiles(working, result);
    const std::vector<ProfileNesting> nesting = profile_nesting(working, result, listed);
    const auto is_outer = [&](std::size_t i) { return listed[i].closed && nesting[i].depth % 2 == 0; };
    std::vector<std::size_t> outers;
    if (!profiles) {
      for (std::size_t i = 0; i < listed.size(); ++i)
        if (is_outer(i))
          outers.push_back(i);
      if (outers.empty())
        throw ValueError("Sketch contains no closed profile; a region needs a closed loop. Components: " + [&] {
          std::string text;
          for (const std::string& part : describe_edge_components(working))
            text += (text.empty() ? "" : "; ") + part;
          return text;
        }());
    } else {
      for (const SketchProfileId& wanted : *profiles) {
        std::size_t found = listed.size();
        for (std::size_t i = 0; i < listed.size(); ++i)
          if (wanted.is_index() ? static_cast<int>(i) == wanted.index() : listed[i].id == wanted.id())
            found = i;
        const std::string name = wanted.to_value().dump();
        if (found == listed.size())
          throw ValueError("there is no sketch profile " + name + " (inspect_sketch_rsketchprofiles lists them)");
        if (!listed[found].closed)
          throw ValueError("sketch profile " + name + " is an open chain: a region needs a closed loop");
        if (!is_outer(found))
          throw ValueError("sketch profile " + name + " is a hole of profile " + std::to_string(nesting[found].parent) +
                           ": pick the region's outer loop (its holes come with it)");
        if (std::find(outers.begin(), outers.end(), found) == outers.end())
          outers.push_back(found);
      }
    }
    // Each region is one recorded face: its outer loop, and the loops directly inside it as holes.
    std::vector<Face> faces;
    for (const std::size_t outer : outers) {
      std::vector<SketchProfileId> holes;
      for (std::size_t j = 0; j < listed.size(); ++j)
        if (nesting[j].parent == static_cast<int>(outer))
          holes.emplace_back(listed[j].id);
      faces.push_back(make_face_from_sketch_rface(sketch, SketchProfileId(listed[outer].id), holes, request));
    }
    return faces;
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
