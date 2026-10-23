// Promoting a solved sketch profile to a Wire or Face.  Internal to the sketch library.
#pragma once

#include <string>
#include <utility>
#include <vector>

#include "convert.hpp"
#include "scad/sketch/profile.hpp"
#include "scad/sketch/sketch.hpp"
#include "scad/topo/shape.hpp"

namespace scad::sketch_detail {

enum class PromotionTarget { Wire, Face };

// One loop of the promoted shape and the OCCT edges its entities became.
struct SourceWire {
  SketchProfileId profile;
  SketchProfile payload;
  std::string role;  // "outer" | "inner"
  ProfileWire built;
};

// What was selected and built, before the shape exists.
struct PromotionLoops {
  SketchSolveResult solve_result;
  SketchProfile profile_payload;
  std::vector<std::pair<SketchProfileId, SketchProfile>> inner_profiles;
  std::vector<SourceWire> source_wires;
};

struct Promotion : PromotionLoops {
  Shape shape;  // a Wire or a Face, with sketch metadata and plain tags applied
};

// _promote_sketch_profile: solve a working copy, pick the profile(s), build the
// wire or face in world coordinates, and attach the promotion metadata.
Promotion promote_sketch_profile(const Sketch& sketch, const SketchProfileId& profile, PromotionTarget target,
                                 const std::vector<SketchProfileId>& inner_profiles,
                                 const SketchSolveRequest& request);

// ---- promotion_semantics.cpp: everything that hangs tags and metadata on the result ----

// _safe_semantic_tag: "<prefix>.<sanitized value>", a valid strict tag.
std::string safe_semantic_tag(const std::string& prefix, const std::string& value);

// The "promotion_map" recorded in the operation params and in shape metadata.
Value sketch_promotion_map(const Sketch& sketch, const SketchProfileId& profile, const SketchProfile& payload,
                           const std::vector<std::pair<SketchProfileId, SketchProfile>>& inner_profiles,
                           const std::string& target_kind);

// _apply_sketch_promotion_metadata: source_sketch / sketch_solve / sketch_promotion
// metadata and the plain sketch.* / sketch_profile.* / sketch_entity.* tags.
void apply_sketch_promotion_metadata(Shape& shape, const Sketch& sketch, const PromotionLoops& promotion);

// _apply_sketch_promotion_identity_tags: the topology-identity bindings
// (sketch.<name>.profile.<id>, sketch.<name>.entity.<id>) with SketchPromotionMap evidence.
void apply_sketch_promotion_identity_tags(Shape& shape, const Sketch& sketch, const PromotionLoops& promotion,
                                          const std::string& operation);

}  // namespace scad::sketch_detail
