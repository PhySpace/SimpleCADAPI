// The tag / metadata half of sketch promotion, kept apart from the geometry so the
// finalize pipeline can take it over without touching the OCCT code.
#include <algorithm>
#include <cctype>

#include "promotion.hpp"
#include "scad/core/error.hpp"
#include "scad/topo/tag_factories.hpp"
#include "scad/topo/tagging.hpp"

namespace scad::sketch_detail {

namespace {

using ProfileList = std::vector<std::pair<SketchProfileId, SketchProfile>>;

bool is_lower_alpha(char c) {
  return c >= 'a' && c <= 'z';
}

std::string sketch_tag_of(const Sketch& sketch) {
  return safe_semantic_tag("sketch", sketch.name() && !sketch.name()->empty() ? *sketch.name() : sketch.sketch_id());
}

std::string profile_tag_of(const SketchProfile& payload) {
  return safe_semantic_tag("sketch_profile", payload.id.empty() ? "profile" : payload.id);
}

// _sketch_topology_tag_local_name: the normalized segment after "name.".
std::string local_name(const std::string& value) {
  const std::string tag = safe_semantic_tag("name", value);
  return tag.substr(tag.find('.') + 1);
}

Value source_sketch_metadata(const Sketch& sketch, const SketchProfileId& profile, const SketchProfile& payload,
                             const ProfileList& inner) {
  Value out = Value::object();
  out.set("sketch_id", sketch.sketch_id());
  out.set("name", sketch.name() ? Value(*sketch.name()) : Value());
  out.set("plane", sketch.plane());
  out.set("profile", profile.to_value());
  out.set("profile_id", payload.id);
  out.set("profile_kind", payload.kind);
  Value::Array inner_values;
  for (const auto& [inner_profile, inner_payload] : inner) {
    Value item = Value::object();
    item.set("profile", inner_profile.to_value());
    item.set("profile_id", inner_payload.id);
    item.set("profile_kind", inner_payload.kind);
    inner_values.push_back(std::move(item));
  }
  out.set("inner_profiles", Value(std::move(inner_values)));
  return out;
}

Value edge_metadata(const Sketch& sketch, const std::string& entity_id, const SketchProfileId& profile,
                    const SketchProfile& payload, const std::string& loop_role) {
  Value out = Value::object();
  out.set("sketch_id", sketch.sketch_id());
  out.set("sketch_name", sketch.name() ? Value(*sketch.name()) : Value());
  out.set("entity_id", entity_id);
  out.set("kind", sketch.entities().at(entity_id).kind);
  out.set("profile", profile.to_value());
  out.set("profile_id", payload.id);
  out.set("loop_role", loop_role);
  return out;
}

Value topology_name(const std::string& kind, const std::string& name, const std::string& local) {
  Value out = Value::object();
  out.set("kind", kind);
  out.set("name", name);
  out.set("local_name", local);
  return out;
}

TagBinding identity_binding(const std::string& tag, const std::string& kind, const std::string& local,
                            const std::string& operation, const Sketch& sketch, const std::string& profile_id,
                            const std::string& target_topo_id, const std::optional<std::string>& entity_id) {
  const std::string rule_id = "simplecad.sketch_promotion_topology_name";
  const std::string key = rule_id + "|" + operation + "|" + sketch.sketch_id() + "|" + profile_id + "|" +
                          entity_id.value_or("") + "|" + target_topo_id + "|" + tag;

  Value promotion = Value::object();
  promotion.set("sketch_id", sketch.sketch_id());
  promotion.set("profile_id", profile_id);
  if (entity_id)
    promotion.set("entity_id", *entity_id);
  Value evidence = Value::object();
  evidence.set("operation", operation);
  evidence.set("target_topo_id", target_topo_id);
  evidence.set("evidence_method", "SketchPromotionMap");
  evidence.set("sketch_promotion", std::move(promotion));
  evidence.set("topology_name", topology_name(kind, tag, local));

  TagBinding binding;
  binding.tag = tag;
  binding.policy.mut().producer.kind = TagProducerKind::AutoRule;
  binding.policy.mut().producer.rule_id = rule_id;
  binding.policy.mut().producer.rule_version = "1.0";
  binding.policy.mut().target.kind = TagTargetKind::ScopeRoot;
  binding.policy.mut().propagation.topology =
      kind == "face" ? TopologyPropagation::Downward : TopologyPropagation::Local;
  binding.policy.mut().propagation.lineage = LineagePolicy::ContinuationFragment;
  binding.evidence.mut().kind = TagEvidenceKind::TopologyChange;
  binding.evidence.mut().data = std::move(evidence);
  binding.certainty = TagCertainty::Proven;
  binding.lifecycle = TagLifecycle::Recompute;
  binding.binding_id = "tag_binding_" + uuid5_url_hex(key);
  return binding;
}

const SourceWire& source_wire_for(const PromotionLoops& promotion, const TopoDS_Shape& wire) {
  const SourceWire* found = nullptr;
  int matches = 0;
  for (const SourceWire& source : promotion.source_wires) {
    if (source.built.wire.wrapped().IsSame(wire)) {
      found = &source;
      ++matches;
    }
  }
  if (matches != 1)
    throw ValueError("Sketch promotion cannot establish exact profile-to-wire correspondence");
  return *found;
}

struct EdgeSource {
  const SourceWire* loop;
  std::string entity_id;
};

EdgeSource edge_source_for(const PromotionLoops& promotion, const TopoDS_Shape& edge) {
  const SourceWire* loop = nullptr;
  const std::string* entity_id = nullptr;
  int matches = 0;
  for (const SourceWire& source : promotion.source_wires) {
    for (const auto& [id, source_edge] : source.built.entity_edges) {
      if (source_edge.IsSame(edge)) {
        loop = &source;
        entity_id = &id;
        ++matches;
      }
    }
  }
  if (matches != 1)
    throw ValueError("Sketch promotion cannot establish exact entity-to-edge correspondence");
  return {loop, *entity_id};
}

std::vector<Wire> wires_of_shape(const Shape& shape) {
  if (shape.kind() == Kind::Wire)
    return {Wire(shape)};
  return Face(shape).wires();
}

std::vector<Edge> edges_of_shape(const Shape& shape) {
  if (shape.kind() == Kind::Wire)
    return Wire(shape).edges();
  return Face(shape).edges();
}

}  // namespace

std::string safe_semantic_tag(const std::string& prefix, const std::string& value) {
  // str(value or "unnamed").strip().lower()
  std::string raw = value;
  const auto not_space = [](unsigned char c) { return !std::isspace(c); };
  raw.erase(raw.begin(), std::find_if(raw.begin(), raw.end(), not_space));
  raw.erase(std::find_if(raw.rbegin(), raw.rend(), not_space).base(), raw.end());
  if (raw.empty())
    raw = "unnamed";
  std::transform(raw.begin(), raw.end(), raw.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

  // Runs of anything outside [a-z0-9_-] become one separator; empty segments vanish.
  std::vector<std::string> segments;
  std::string current;
  const auto flush = [&] {
    if (current.empty())
      return;
    if (!is_lower_alpha(current.front()))
      current = "id_" + current;
    segments.push_back(std::move(current));
    current.clear();
  };
  for (const char c : raw) {
    const bool allowed = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-';
    if (allowed) {
      current += c;
    } else {
      flush();
    }
  }
  flush();
  if (segments.empty())
    segments.push_back("unnamed");
  std::string tag = prefix + ".";
  for (std::size_t i = 0; i < segments.size(); ++i)
    tag += (i == 0 ? "" : ".") + segments[i];
  return normalize_tag(tag, /*strict=*/true);
}

Value sketch_promotion_map(const Sketch& sketch, const SketchProfileId& profile, const SketchProfile& payload,
                           const ProfileList& inner_profiles, const std::string& target_kind) {
  const std::string sketch_tag = sketch_tag_of(sketch);
  const std::string profile_local = local_name(payload.id.empty() ? "profile" : payload.id);

  struct LoopSpec {
    const SketchProfileId* profile;
    const SketchProfile* payload;
    const char* role;
  };
  std::vector<LoopSpec> loop_specs{{&profile, &payload, "outer"}};
  for (const auto& [inner_profile, inner_payload] : inner_profiles) {
    loop_specs.push_back({&inner_profile, &inner_payload, "inner"});
  }

  Value::Array edges;
  Value::Array loops;
  for (const LoopSpec& spec : loop_specs) {
    const std::string loop_sketch_tag = sketch_tag_of(sketch);
    const std::string loop_profile_tag = profile_tag_of(*spec.payload);
    Value::Array loop_edges;
    for (const std::string& entity_id : spec.payload->entity_ids) {
      const std::string entity_tag = safe_semantic_tag("sketch_entity", entity_id);
      const std::string entity_local = local_name(entity_id);
      Value edge = Value::object();
      edge.set("entity_id", entity_id);
      edge.set("profile", spec.profile->to_value());
      edge.set("profile_id", spec.payload->id);
      edge.set("loop_role", spec.role);
      edge.set("target_kind", "edge");
      edge.set("tags", Value(Value::Array{Value(loop_sketch_tag), Value(loop_profile_tag), Value(entity_tag)}));
      edge.set("topology_name", topology_name("edge", loop_sketch_tag + ".entity." + entity_local, entity_local));
      Value metadata = Value::object();
      metadata.set("sketch_ref", edge_metadata(sketch, entity_id, *spec.profile, *spec.payload, spec.role));
      edge.set("metadata", std::move(metadata));
      loop_edges.push_back(edge);
      edges.push_back(std::move(edge));
    }
    const std::string loop_local = local_name(spec.payload->id.empty() ? "profile" : spec.payload->id);
    Value loop = Value::object();
    loop.set("role", spec.role);
    loop.set("profile", spec.profile->to_value());
    loop.set("profile_id", spec.payload->id);
    loop.set("profile_kind", spec.payload->kind);
    loop.set("topology_name", topology_name("wire", loop_sketch_tag + ".profile." + loop_local, loop_local));
    loop.set("edges", Value(std::move(loop_edges)));
    loops.push_back(std::move(loop));
  }

  Value out = Value::object();
  out.set("schema_version", "2.0");
  out.set("profile", profile.to_value());
  out.set("profile_id", payload.id);
  out.set("profile_kind", payload.kind);
  out.set("tags", Value(Value::Array{Value(sketch_tag), Value(profile_tag_of(payload))}));
  out.set("topology_name", topology_name(target_kind.empty() ? "profile" : target_kind,
                                         sketch_tag + ".profile." + profile_local, profile_local));
  out.set("loops", Value(std::move(loops)));
  out.set("edges", Value(std::move(edges)));
  return out;
}

void apply_sketch_promotion_metadata(Shape& shape, const Sketch& sketch, const PromotionLoops& promotion) {
  const Value source_sketch = source_sketch_metadata(sketch, promotion.source_wires.front().profile,
                                                     promotion.profile_payload, promotion.inner_profiles);
  const Value solve_snapshot = promotion.solve_result.to_value();
  const Value promotion_map =
      sketch_promotion_map(sketch, promotion.source_wires.front().profile, promotion.profile_payload,
                           promotion.inner_profiles, shape.kind() == Kind::Wire ? "wire" : "face");
  const std::string sketch_tag = sketch_tag_of(sketch);
  const std::string profile_tag = profile_tag_of(promotion.profile_payload);

  shape.set_metadata("source_sketch", source_sketch);
  shape.set_metadata("sketch_solve", solve_snapshot);
  shape.set_metadata("sketch_promotion", promotion_map);
  shape.apply_tag(sketch_tag, /*propagate=*/false);
  shape.apply_tag(profile_tag, /*propagate=*/false);

  for (Wire& wire : wires_of_shape(shape)) {
    const SourceWire& loop = source_wire_for(promotion, wire.wrapped());
    wire.set_metadata("source_sketch", source_sketch);
    wire.set_metadata("sketch_solve", solve_snapshot);
    wire.set_metadata("sketch_promotion", promotion_map);
    wire.set_metadata("sketch_profile", source_sketch_metadata(sketch, loop.profile, loop.payload, {}));
    wire.apply_tag(sketch_tag_of(sketch), /*propagate=*/false);
    wire.apply_tag(profile_tag_of(loop.payload), /*propagate=*/false);
  }

  for (Edge& edge : edges_of_shape(shape)) {
    const EdgeSource source = edge_source_for(promotion, edge.wrapped());
    const SourceWire& loop = *source.loop;
    edge.set_metadata("sketch_ref", edge_metadata(sketch, source.entity_id, loop.profile, loop.payload, loop.role));
    edge.set_metadata("source_sketch", source_sketch);
    edge.apply_tag(sketch_tag_of(sketch), /*propagate=*/false);
    edge.apply_tag(profile_tag_of(loop.payload), /*propagate=*/false);
    edge.apply_tag(safe_semantic_tag("sketch_entity", source.entity_id), /*propagate=*/false);
  }
}

void apply_sketch_promotion_identity_tags(Shape& shape, const Sketch& sketch, const PromotionLoops& promotion,
                                          const std::string& operation) {
  const std::string sketch_prefix = sketch_tag_of(sketch);
  const SketchProfile& payload = promotion.profile_payload;
  const std::string profile_id = payload.id.empty() ? "profile" : payload.id;
  const std::string profile_local = local_name(profile_id);
  const std::string kind = shape.kind() == Kind::Wire ? "wire" : "face";
  shape.add_binding(identity_binding(sketch_prefix + ".profile." + profile_local, kind, profile_local, operation,
                                     sketch, profile_id, shape.topo_id(), std::nullopt));

  if (shape.kind() == Kind::Face) {
    for (Wire& wire : Face(shape).wires()) {
      const SourceWire& loop = source_wire_for(promotion, wire.wrapped());
      const std::string loop_id = loop.payload.id.empty() ? "profile" : loop.payload.id;
      const std::string loop_local = local_name(loop_id);
      wire.add_binding(identity_binding(sketch_prefix + ".profile." + loop_local, "wire", loop_local, operation, sketch,
                                        loop_id, wire.topo_id(), std::nullopt));
    }
  }

  for (Edge& edge : edges_of_shape(shape)) {
    const EdgeSource source = edge_source_for(promotion, edge.wrapped());
    const std::string loop_id = source.loop->payload.id.empty() ? "profile" : source.loop->payload.id;
    const std::string entity_local = local_name(source.entity_id);
    edge.add_binding(identity_binding(sketch_prefix + ".entity." + entity_local, "edge", entity_local, operation,
                                      sketch, loop_id, edge.topo_id(), source.entity_id));
  }
}

}  // namespace scad::sketch_detail
