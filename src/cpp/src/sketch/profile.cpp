#include "scad/sketch/profile.hpp"

#include <algorithm>
#include <cmath>
#include <set>

#include "scad/core/error.hpp"

namespace scad {

namespace {

bool is_edge_kind(const std::string& kind) { return kind == kLineKind || kind == kArcKind || kind == kBSplineKind; }

std::pair<std::string, std::string> edge_endpoints(const SketchEntity& entity) {
  return {entity.point_id("start"), entity.point_id("end")};
}

// Non-construction line / arc / bspline ids, in entity order.
std::vector<std::string> edge_entity_ids(const Sketch& sketch) {
  std::vector<std::string> ids;
  for (const auto& [id, entity] : sketch.entities()) {
    if (is_edge_kind(entity.kind) && !entity.construction) ids.push_back(id);
  }
  return ids;
}

std::size_t entity_position(const Sketch& sketch, const std::string& id) {
  std::size_t position = 0;
  for (const auto& item : sketch.entities()) {
    if (item.first == id) return position;
    ++position;
  }
  return position;
}

// _edge_component: the entities connected to `first_edge` through shared points,
// in entity order.
std::vector<std::string> edge_component(const Sketch& sketch, const std::string& first_edge,
                                        const std::set<std::string>& candidates) {
  std::vector<std::string> queue{first_edge};
  std::set<std::string> seen_edges;
  std::set<std::string> seen_points;
  for (std::size_t cursor = 0; cursor < queue.size(); ++cursor) {
    const std::string edge_id = queue[cursor];
    if (!seen_edges.insert(edge_id).second) continue;
    const auto [start, end] = edge_endpoints(sketch.entities().at(edge_id));
    for (const std::string& point_id : {start, end}) {
      if (!seen_points.insert(point_id).second) continue;
      for (const std::string& other_id : candidates) {
        const auto [other_start, other_end] = edge_endpoints(sketch.entities().at(other_id));
        if (point_id == other_start || point_id == other_end) queue.push_back(other_id);
      }
    }
  }
  std::vector<std::string> component(seen_edges.begin(), seen_edges.end());
  std::sort(component.begin(), component.end(), [&sketch](const std::string& a, const std::string& b) {
    return entity_position(sketch, a) < entity_position(sketch, b);
  });
  return component;
}

struct OrderedPath {
  std::vector<std::string> point_ids;
  std::vector<std::pair<std::string, bool>> oriented_edges;  // (edge id, reversed)
  bool closed = false;
};

// _ordered_edge_path: a component whose vertices all have degree <= 2 is a simple
// cycle (no degree-1 vertices) or a simple open chain (exactly two); anything else
// has no ordered edge sequence.
std::optional<OrderedPath> ordered_edge_path(const Sketch& sketch, const std::vector<std::string>& edge_ids) {
  OrderedMap<std::vector<std::string>> adjacency;
  for (const std::string& edge_id : edge_ids) {
    const auto [start, end] = edge_endpoints(sketch.entities().at(edge_id));
    adjacency[start].push_back(edge_id);
    adjacency[end].push_back(edge_id);
  }
  if (adjacency.empty()) return std::nullopt;
  for (const auto& item : adjacency) {
    if (item.second.size() > 2) return std::nullopt;
  }
  std::vector<std::string> endpoints;
  for (const auto& item : adjacency) {
    if (item.second.size() == 1) endpoints.push_back(item.first);
  }

  OrderedPath path;
  std::string start_point;
  std::string start_edge;
  if (endpoints.size() == 2) {
    path.closed = false;
    start_point = endpoints[0];
    start_edge = adjacency.at(start_point)[0];
  } else if (endpoints.empty()) {
    path.closed = true;
    start_edge = edge_ids[0];
    start_point = edge_endpoints(sketch.entities().at(start_edge)).first;
  } else {
    return std::nullopt;
  }

  const auto [first_start, first_end] = edge_endpoints(sketch.entities().at(start_edge));
  std::string current_point;
  bool reversed_edge = false;
  if (first_start == start_point) {
    current_point = first_end;
  } else {
    current_point = first_start;
    reversed_edge = true;
  }
  std::set<std::string> used_edges{start_edge};
  path.point_ids = {start_point, current_point};
  path.oriented_edges.emplace_back(start_edge, reversed_edge);

  while (true) {
    if (path.closed && current_point == start_point) break;
    std::string next_edge;
    for (const std::string& candidate : adjacency.at(current_point)) {
      if (used_edges.count(candidate) == 0) {
        next_edge = candidate;
        break;
      }
    }
    if (next_edge.empty()) {
      if (path.closed || used_edges.size() != edge_ids.size()) return std::nullopt;
      break;
    }
    used_edges.insert(next_edge);
    const auto [next_start, next_end] = edge_endpoints(sketch.entities().at(next_edge));
    reversed_edge = next_start != current_point;
    path.oriented_edges.emplace_back(next_edge, reversed_edge);
    current_point = reversed_edge ? next_start : next_end;
    if (!(path.closed && current_point == start_point)) path.point_ids.push_back(current_point);
  }
  if (used_edges.size() != edge_ids.size()) return std::nullopt;
  if (path.closed && current_point != start_point) return std::nullopt;
  return path;
}

std::string join(const std::vector<std::string>& parts, const char* separator) {
  std::string out;
  for (const std::string& part : parts) {
    if (!out.empty()) out += separator;
    out += part;
  }
  return out;
}

std::string describe_edge_component(const Sketch& sketch, const std::vector<std::string>& edge_ids) {
  OrderedMap<std::vector<std::string>> adjacency;
  for (const std::string& edge_id : edge_ids) {
    const auto [start, end] = edge_endpoints(sketch.entities().at(edge_id));
    adjacency[start].push_back(edge_id);
    adjacency[end].push_back(edge_id);
  }
  const std::string listed = join(edge_ids, "/");
  for (const auto& item : adjacency) {
    if (item.second.size() > 2) {
      return "branched edge set (" + listed + ") with branch point '" + item.first + "' carrying " +
             std::to_string(item.second.size()) + " edges";
    }
  }
  std::vector<std::string> endpoints;
  for (const auto& item : adjacency) {
    if (item.second.size() == 1) endpoints.push_back(item.first);
  }
  if (endpoints.size() == 2) {
    return "open chain (" + listed + ") from '" + endpoints[0] + "' to '" + endpoints[1] + "'";
  }
  if (endpoints.empty()) return "closed loop (" + listed + ")";
  return "irregular edge set (" + listed + ")";
}

std::vector<SketchProfile> edge_path_profiles(const Sketch& sketch, const std::shared_ptr<const SketchSolveResult>& result) {
  const std::vector<std::string> edge_ids = edge_entity_ids(sketch);
  std::set<std::string> unused(edge_ids.begin(), edge_ids.end());
  std::vector<SketchProfile> profiles;
  while (!unused.empty()) {
    // The unused edge that comes first in entity order.
    const std::string first_edge = *std::find_if(edge_ids.begin(), edge_ids.end(),
                                                 [&unused](const std::string& id) { return unused.count(id) != 0; });
    const std::vector<std::string> component = edge_component(sketch, first_edge, unused);
    for (const std::string& id : component) unused.erase(id);
    const std::optional<OrderedPath> ordered = ordered_edge_path(sketch, component);
    if (!ordered) continue;
    SketchProfile profile;
    profile.id = component[0];
    profile.kind = ordered->closed ? "edge_loop" : "edge_chain";
    profile.closed = ordered->closed;
    for (const auto& [edge_id, reversed] : ordered->oriented_edges) {
      profile.entity_ids.push_back(edge_id);
      profile.reversed.push_back(reversed);
    }
    profile.point_ids = ordered->point_ids;
    if (!ordered->closed) profile.endpoints = {ordered->point_ids.front(), ordered->point_ids.back()};
    profile.solve = result;
    profiles.push_back(std::move(profile));
  }
  return profiles;
}

}  // namespace

std::vector<std::string> describe_edge_components(const Sketch& sketch) {
  const std::vector<std::string> edge_ids = edge_entity_ids(sketch);
  std::set<std::string> unused(edge_ids.begin(), edge_ids.end());
  std::vector<std::string> descriptions;
  while (!unused.empty()) {
    const std::string first_edge = *std::find_if(edge_ids.begin(), edge_ids.end(),
                                                 [&unused](const std::string& id) { return unused.count(id) != 0; });
    const std::vector<std::string> component = edge_component(sketch, first_edge, unused);
    for (const std::string& id : component) unused.erase(id);
    descriptions.push_back(describe_edge_component(sketch, component));
  }
  return descriptions;
}

std::vector<SketchProfile> sketch_profiles(const Sketch& sketch, const SketchSolveResult& result) {
  std::vector<SketchProfile> profiles;
  const Vec3 normal = sketch.plane_normal();
  const auto solved_point = [&result](const std::string& id) { return result.solved_points.at(id); };
  for (const auto& [entity_id, entity] : sketch.entities()) {
    if (entity.construction) continue;
    if (entity.kind == kCircleKind) {
      SketchProfile profile;
      profile.id = entity_id;
      profile.kind = "circle";
      profile.entity_ids = {entity_id};
      profile.center = sketch.point3(solved_point(entity.point_id("center")));
      profile.radius = result.solved_scalars.at("circle:" + entity_id + ":radius");
      profile.normal = normal;
      profiles.push_back(std::move(profile));
    }
    if (entity.kind == kEllipseKind) {
      const Vec3 center = sketch.point3(solved_point(entity.point_id("center")));
      const Vec3 major = sketch.point3(solved_point(entity.point_id("major")));
      const Vec3 minor = sketch.point3(solved_point(entity.point_id("minor")));
      SketchProfile profile;
      profile.id = entity_id;
      profile.kind = "ellipse";
      profile.entity_ids = {entity_id};
      profile.center = center;
      profile.major_radius = center.distance(major);
      profile.minor_radius = center.distance(minor);
      profile.major_direction = major - center;
      profile.normal = normal;
      profiles.push_back(std::move(profile));
    }
  }
  auto edge_profiles = edge_path_profiles(sketch, std::make_shared<const SketchSolveResult>(result));
  profiles.insert(profiles.end(), std::make_move_iterator(edge_profiles.begin()),
                  std::make_move_iterator(edge_profiles.end()));
  return profiles;
}

SketchProfile select_sketch_profile(const Sketch& sketch, const SketchProfileId& profile,
                                    const SketchSolveResult& result, bool require_closed) {
  std::vector<SketchProfile> profiles = sketch_profiles(sketch, result);
  if (require_closed) {
    std::vector<SketchProfile> closed;
    for (SketchProfile& item : profiles) {
      if (item.closed) closed.push_back(std::move(item));
    }
    if (closed.empty()) {
      throw ValueError(
          "Sketch contains no closed profile; face promotion requires a closed loop. Components: " +
          join(describe_edge_components(sketch), "; "));
    }
    profiles = std::move(closed);
  }
  if (profiles.empty()) {
    const std::vector<std::string> descriptions = describe_edge_components(sketch);
    const std::string detail = descriptions.empty() ? "The sketch has no non-construction edge entities."
                                                    : "Components: " + join(descriptions, "; ");
    throw ValueError("Sketch contains no promotable closed loop or open chain. " + detail);
  }
  if (!profile.is_index()) {
    for (SketchProfile& item : profiles) {
      if (item.id == profile.id()) return std::move(item);
    }
    throw ValueError("Unknown sketch profile '" + profile.id() + "'");
  }
  const int index = profile.index();
  if (index < 0 || index >= static_cast<int>(profiles.size())) {
    throw ValueError("Sketch profile index " + std::to_string(index) + " is out of range");
  }
  return std::move(profiles[static_cast<std::size_t>(index)]);
}

}  // namespace scad
