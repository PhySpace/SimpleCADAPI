#include <set>

#include <BRepCheck_Analyzer.hxx>
#include <TopoDS.hxx>

#include "promotion.hpp"
#include "scad/core/error.hpp"
#include "scad/kernel/features.hpp"

namespace scad::sketch_detail {

namespace {

// The wire, or its reverse, whichever winds counter-clockwise about `expected_normal`.
TopoDS_Wire aligned_wire(const Wire& wire, const Vec3& expected_normal) {
  const Face loop_face(kernel::make_face_from_wire(TopoDS::Wire(wire.wrapped())));
  const Vec3 loop_normal = loop_face.normal_at();
  return expected_normal.dot(loop_normal) >= 0.0 ? TopoDS::Wire(wire.wrapped())
                                                 : TopoDS::Wire(wire.wrapped().Reversed());
}

Face build_face(const PromotionLoops& promotion, const Sketch& sketch) {
  const Vec3 expected_normal = sketch.plane_normal().normalized();
  const SourceWire& outer = promotion.source_wires.front();
  std::vector<TopoDS_Wire> inner_wires;
  for (std::size_t i = 1; i < promotion.source_wires.size(); ++i) {
    inner_wires.push_back(aligned_wire(promotion.source_wires[i].built.wire, expected_normal));
  }
  const TopoDS_Wire outer_wire = aligned_wire(outer.built.wire, expected_normal);
  const TopoDS_Face raw_face = inner_wires.empty() ? kernel::make_face_from_wire(outer_wire)
                                                   : kernel::make_face_from_wires(outer_wire, inner_wires);
  if (!inner_wires.empty() && !BRepCheck_Analyzer(raw_face).IsValid()) {
    throw ValueError(
        "Sketch hole profiles must lie strictly inside the outer profile and must not touch or intersect another loop");
  }
  Face face(raw_face);
  if (expected_normal.dot(face.normal_at()) < 0.0) face = Face(TopoDS::Face(raw_face.Reversed()));
  return face;
}

}  // namespace

Promotion promote_sketch_profile(const Sketch& sketch, const SketchProfileId& profile, PromotionTarget target,
                                 const std::vector<SketchProfileId>& inner_profiles,
                                 const SketchSolveRequest& request) {
  Sketch working = sketch.clone(/*include_solve=*/false);
  PromotionLoops promotion;
  promotion.solve_result = working.solve(request);

  // A face needs a closed outer loop (and closed inner loops); a wire accepts closed
  // loops and open chains alike -- consumers like extrude enforce their own closedness.
  const bool require_closed = target == PromotionTarget::Face;
  promotion.profile_payload = select_sketch_profile(sketch, profile, promotion.solve_result, require_closed);
  std::set<std::string> seen_profile_ids{promotion.profile_payload.id};
  for (const SketchProfileId& inner : inner_profiles) {
    SketchProfile payload = select_sketch_profile(sketch, inner, promotion.solve_result, require_closed);
    if (!seen_profile_ids.insert(payload.id).second) {
      throw ValueError("Sketch profile '" + payload.id + "' was selected more than once");
    }
    promotion.inner_profiles.emplace_back(inner, std::move(payload));
  }

  promotion.source_wires.push_back(
      {profile, promotion.profile_payload, "outer", wire_from_profile(sketch, promotion.profile_payload)});
  Shape shape = promotion.source_wires.front().built.wire;
  if (target == PromotionTarget::Wire) {
    if (!promotion.inner_profiles.empty()) throw ValueError("A Wire promotion accepts exactly one sketch profile");
  } else {
    for (const auto& [inner_profile, inner_payload] : promotion.inner_profiles) {
      promotion.source_wires.push_back({inner_profile, inner_payload, "inner", wire_from_profile(sketch, inner_payload)});
    }
    shape = build_face(promotion, sketch);
  }
  apply_sketch_promotion_metadata(shape, sketch, promotion);
  return Promotion{std::move(promotion), std::move(shape)};
}

}  // namespace scad::sketch_detail
