// Profiles: the closed loops and open chains a solved sketch offers for promotion.
//
// Port of Sketch._profile_payload / _profiles_from_solution / _edge_path_profiles.
// A profile is either a free circle or ellipse, or a connected component of
// line / arc / B-spline entities that forms a simple loop or chain.
#pragma once

#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/sketch/sketch.hpp"

namespace scad {

// `profile: int | str` -- an index into the profile list or a profile id.
class SketchProfileId {
 public:
  SketchProfileId(int index = 0) : index_(index) {}        // NOLINT(google-explicit-constructor)
  SketchProfileId(std::string id) : id_(std::move(id)) {}  // NOLINT(google-explicit-constructor)
  SketchProfileId(const char* id) : id_(id) {}             // NOLINT(google-explicit-constructor)

  bool is_index() const noexcept { return !id_.has_value(); }
  int index() const noexcept { return index_; }
  const std::string& id() const { return *id_; }
  // The JSON form recorded in metadata: a number or a string.
  Value to_value() const { return id_ ? Value(*id_) : Value(index_); }

 private:
  int index_ = 0;
  std::optional<std::string> id_;
};

struct SketchProfile {
  std::string id;
  std::string kind;  // "circle" | "ellipse" | "edge_loop" | "edge_chain"
  bool closed = true;
  std::vector<std::string> entity_ids;

  // circle / ellipse, in world coordinates
  Vec3 center;
  Vec3 normal;
  double radius = 0.0;
  double major_radius = 0.0;
  double minor_radius = 0.0;
  Vec3 major_direction;

  // edge_loop / edge_chain
  std::vector<bool> reversed;
  std::vector<std::string> point_ids;
  std::vector<std::string> endpoints;  // open chains: first and last point id
  std::shared_ptr<const SketchSolveResult> solve;
};

// Every profile of the solved sketch: circles and ellipses in entity order, then
// the edge components in the order of their first entity.
std::vector<SketchProfile> sketch_profiles(const Sketch& sketch, const SketchSolveResult& result);

// Sketch._profile_payload.  `require_closed`: faces cannot use open chains.
// ValueError with the Python text (component listing included) when nothing fits.
SketchProfile select_sketch_profile(const Sketch& sketch, const SketchProfileId& profile,
                                    const SketchSolveResult& result, bool require_closed = false);

// "closed loop (a/b/c)", "open chain (a/b) from 'p' to 'q'", "branched edge set (...)", ...
std::vector<std::string> describe_edge_components(const Sketch& sketch);

}  // namespace scad
