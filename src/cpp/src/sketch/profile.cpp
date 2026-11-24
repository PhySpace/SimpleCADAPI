#include "scad/sketch/profile.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <set>
#include <unordered_map>

#include "scad/core/error.hpp"

namespace scad {

namespace {

bool is_edge_kind(const std::string& kind) {
  return kind == kLineKind || kind == kArcKind || kind == kBSplineKind;
}

std::pair<std::string, std::string> edge_endpoints(const SketchEntity& entity) {
  return {entity.point_id("start"), entity.point_id("end")};
}

// Non-construction line / arc / bspline ids, in entity order.
std::vector<std::string> edge_entity_ids(const Sketch& sketch) {
  std::vector<std::string> ids;
  for (const auto& [id, entity] : sketch.entities()) {
    if (is_edge_kind(entity.kind) && !entity.construction)
      ids.push_back(id);
  }
  return ids;
}

// Connect by entity id, never by coordinates. Emit groups and their members in original
// insertion order independently of the hash table order (profile indices and diagnostics use it).
std::vector<std::vector<std::string>> edge_components(const Sketch& sketch) {
  const auto ids = edge_entity_ids(sketch);
  std::vector<std::size_t> parent(ids.size());
  std::iota(parent.begin(), parent.end(), std::size_t{0});
  const auto root = [&](std::size_t i) {
    while (parent[i] != i) {
      parent[i] = parent[parent[i]];
      i = parent[i];
    }
    return i;
  };
  std::unordered_map<std::string, std::size_t> first;
  for (std::size_t i = 0; i < ids.size(); ++i) {
    const auto [start, end] = edge_endpoints(sketch.entities().at(ids[i]));
    for (const auto* point : {&start, &end}) {
      const auto [it, inserted] = first.try_emplace(*point, i);
      if (!inserted)
        parent[root(i)] = root(it->second);
    }
  }
  std::vector<std::vector<std::string>> groups;
  std::vector<std::size_t> slot(ids.size(), ids.size());
  for (std::size_t i = 0; i < ids.size(); ++i) {
    auto& index = slot[root(i)];
    if (index == ids.size()) {
      index = groups.size();
      groups.emplace_back();
    }
    groups[index].push_back(ids[i]);
  }
  return groups;
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
  if (adjacency.empty())
    return std::nullopt;
  for (const auto& item : adjacency) {
    if (item.second.size() > 2)
      return std::nullopt;
  }
  std::vector<std::string> endpoints;
  for (const auto& item : adjacency) {
    if (item.second.size() == 1)
      endpoints.push_back(item.first);
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
    if (path.closed && current_point == start_point)
      break;
    std::string next_edge;
    for (const std::string& candidate : adjacency.at(current_point)) {
      if (used_edges.count(candidate) == 0) {
        next_edge = candidate;
        break;
      }
    }
    if (next_edge.empty()) {
      if (path.closed || used_edges.size() != edge_ids.size())
        return std::nullopt;
      break;
    }
    used_edges.insert(next_edge);
    const auto [next_start, next_end] = edge_endpoints(sketch.entities().at(next_edge));
    reversed_edge = next_start != current_point;
    path.oriented_edges.emplace_back(next_edge, reversed_edge);
    current_point = reversed_edge ? next_start : next_end;
    if (!(path.closed && current_point == start_point))
      path.point_ids.push_back(current_point);
  }
  if (used_edges.size() != edge_ids.size())
    return std::nullopt;
  if (path.closed && current_point != start_point)
    return std::nullopt;
  return path;
}

std::string join(const std::vector<std::string>& parts, const char* separator) {
  std::string out;
  for (const std::string& part : parts) {
    if (!out.empty())
      out += separator;
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
    if (item.second.size() == 1)
      endpoints.push_back(item.first);
  }
  if (endpoints.size() == 2) {
    return "open chain (" + listed + ") from '" + endpoints[0] + "' to '" + endpoints[1] + "'";
  }
  if (endpoints.empty())
    return "closed loop (" + listed + ")";
  return "irregular edge set (" + listed + ")";
}

std::vector<SketchProfile> edge_path_profiles(const Sketch& sketch,
                                              const std::shared_ptr<const SketchSolveResult>& result) {
  std::vector<SketchProfile> profiles;
  for (const auto& component : edge_components(sketch)) {
    const std::optional<OrderedPath> ordered = ordered_edge_path(sketch, component);
    if (!ordered)
      continue;
    SketchProfile profile;
    profile.id = component[0];
    profile.kind = ordered->closed ? "edge_loop" : "edge_chain";
    profile.closed = ordered->closed;
    for (const auto& [edge_id, reversed] : ordered->oriented_edges) {
      profile.entity_ids.push_back(edge_id);
      profile.reversed.push_back(reversed);
    }
    profile.point_ids = ordered->point_ids;
    if (!ordered->closed)
      profile.endpoints = {ordered->point_ids.front(), ordered->point_ids.back()};
    profile.solve = result;
    profiles.push_back(std::move(profile));
  }
  return profiles;
}

}  // namespace

std::vector<std::string> describe_edge_components(const Sketch& sketch) {
  std::vector<std::string> descriptions;
  for (const auto& component : edge_components(sketch)) {
    descriptions.push_back(describe_edge_component(sketch, component));
  }
  return descriptions;
}

std::vector<SketchProfile> sketch_profiles(const Sketch& sketch, const SketchSolveResult& result) {
  std::vector<SketchProfile> profiles;
  const Vec3 normal = sketch.plane_normal();
  const auto solved_point = [&result](const std::string& id) { return result.solved_points.at(id); };
  for (const auto& [entity_id, entity] : sketch.entities()) {
    if (entity.construction)
      continue;
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
  // The index is the one inspect_sketch_rsketchprofiles lists (open chains included), for a face as for a wire.
  std::vector<SketchProfile> profiles = sketch_profiles(sketch, result);
  const bool any_closed =
      std::any_of(profiles.begin(), profiles.end(), [](const SketchProfile& p) { return p.closed; });
  if (require_closed && !any_closed) {
    throw ValueError("Sketch contains no closed profile; face promotion requires a closed loop. Components: " +
                     join(describe_edge_components(sketch), "; "));
  }
  if (profiles.empty()) {
    const std::vector<std::string> descriptions = describe_edge_components(sketch);
    const std::string detail = descriptions.empty() ? "The sketch has no non-construction edge entities."
                                                    : "Components: " + join(descriptions, "; ");
    throw ValueError("Sketch contains no promotable closed loop or open chain. " + detail);
  }
  std::size_t chosen = profiles.size();
  if (!profile.is_index()) {
    for (std::size_t i = 0; i < profiles.size(); ++i)
      if (profiles[i].id == profile.id())
        chosen = i;
    if (chosen == profiles.size())
      throw ValueError("Unknown sketch profile '" + profile.id() + "'");
  } else {
    const int index = profile.index();
    if (index < 0 || index >= static_cast<int>(profiles.size()))
      throw ValueError("Sketch profile index " + std::to_string(index) + " is out of range (the sketch has " +
                       std::to_string(profiles.size()) + " profiles, inspect_sketch_rsketchprofiles lists them)");
    chosen = static_cast<std::size_t>(index);
  }
  if (require_closed && !profiles[chosen].closed) {
    std::vector<std::string> closed;
    for (std::size_t i = 0; i < profiles.size(); ++i)
      if (profiles[i].closed)
        closed.push_back(std::to_string(i));
    throw ValueError("Sketch profile " + profile.to_value().dump() + " ('" + profiles[chosen].id +
                     "') is an open chain: a face needs a closed one (closed profiles: " + join(closed, ", ") + ")");
  }
  return std::move(profiles[chosen]);
}

}  // namespace scad
