#include "scad/topo/tag_factories.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <set>

#include "scad/core/error.hpp"

namespace scad {

std::array<std::uint8_t, 16> uuid5_url_bytes(std::string_view name);

namespace {

// ---------------------------------------------------------------------------
// SHA-1, for uuid5.  Not used for security: it reproduces Python's deterministic ids.
// ---------------------------------------------------------------------------
std::array<std::uint8_t, 20> sha1(const std::uint8_t* message, std::size_t length) {
  auto rotl = [](std::uint32_t v, int n) { return (v << n) | (v >> (32 - n)); };
  std::uint32_t h[5] = {0x67452301u, 0xEFCDAB89u, 0x98BADCFEu, 0x10325476u, 0xC3D2E1F0u};

  // Whole 64-byte blocks straight from the input, then the padded tail (one or two blocks).
  const std::uint64_t bit_length = static_cast<std::uint64_t>(length) * 8u;
  std::uint8_t tail[128] = {};
  const std::size_t whole = length / 64 * 64;
  const std::size_t rest = length - whole;
  std::copy(message + whole, message + length, tail);
  tail[rest] = 0x80;
  const std::size_t tail_blocks = rest < 56 ? 1 : 2;
  for (int i = 0; i < 8; ++i) tail[tail_blocks * 64 - 1 - static_cast<std::size_t>(i)] = static_cast<std::uint8_t>((bit_length >> (8 * i)) & 0xFFu);

  auto compress = [&](const std::uint8_t* block) {
    std::uint32_t w[80];
    for (std::size_t i = 0; i < 16; ++i) {
      const std::uint8_t* p = block + i * 4;
      w[i] = (std::uint32_t{p[0]} << 24) | (std::uint32_t{p[1]} << 16) | (std::uint32_t{p[2]} << 8) | std::uint32_t{p[3]};
    }
    for (std::size_t i = 16; i < 80; ++i) w[i] = rotl(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);

    std::uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4];
    for (std::size_t i = 0; i < 80; ++i) {
      std::uint32_t f, k;
      if (i < 20) { f = (b & c) | (~b & d); k = 0x5A827999u; }
      else if (i < 40) { f = b ^ c ^ d; k = 0x6ED9EBA1u; }
      else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDCu; }
      else { f = b ^ c ^ d; k = 0xCA62C1D6u; }
      const std::uint32_t temp = rotl(a, 5) + f + e + k + w[i];
      e = d; d = c; c = rotl(b, 30); b = a; a = temp;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e;
  };
  for (std::size_t block = 0; block < whole; block += 64) compress(message + block);
  for (std::size_t block = 0; block < tail_blocks; ++block) compress(tail + block * 64);

  std::array<std::uint8_t, 20> digest{};
  for (std::size_t i = 0; i < 5; ++i)
    for (std::size_t j = 0; j < 4; ++j) digest[i * 4 + j] = static_cast<std::uint8_t>((h[i] >> (24 - 8 * j)) & 0xFFu);
  return digest;
}

// uuid.NAMESPACE_URL = 6ba7b811-9dad-11d1-80b4-00c04fd430c8
constexpr std::array<std::uint8_t, 16> kNamespaceUrl = {0x6b, 0xa7, 0xb8, 0x11, 0x9d, 0xad, 0x11, 0xd1,
                                                        0x80, 0xb4, 0x00, 0xc0, 0x4f, 0xd4, 0x30, 0xc8};

BindingId deterministic_binding_id(std::string_view key) {
  const auto bytes = uuid5_url_bytes(key);
  std::uint64_t words[2] = {0, 0};
  for (std::size_t i = 0; i < 16; ++i) words[i / 8] = (words[i / 8] << 8) | bytes[i];
  return BindingId::from_words(words[0], words[1]);
}

std::string value_text(const Value& v) {
  // str(x): the evidence values these ids are keyed on are always strings.
  return v.is_string() ? v.as_string() : v.dump();
}

bool starts_with(std::string_view s, std::string_view prefix) { return s.substr(0, prefix.size()) == prefix; }

bool contains(const std::vector<std::string>& list, std::string_view s) {
  return std::find(list.begin(), list.end(), s) != list.end();
}

std::string lower(std::string_view s) {
  std::string out(s);
  std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
    return static_cast<char>(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c);
  });
  return out;
}

std::string strip(std::string_view s) {
  const auto b = s.find_first_not_of(" \t\r\n\f\v");
  if (b == std::string_view::npos) return {};
  const auto e = s.find_last_not_of(" \t\r\n\f\v");
  return std::string(s.substr(b, e - b + 1));
}

}  // namespace

std::array<std::uint8_t, 16> uuid5_url_bytes(std::string_view name) {
  std::uint8_t stack_buffer[256];
  std::string heap_buffer;
  std::uint8_t* message = stack_buffer;
  if (kNamespaceUrl.size() + name.size() > sizeof stack_buffer) {
    heap_buffer.resize(kNamespaceUrl.size() + name.size());
    message = reinterpret_cast<std::uint8_t*>(heap_buffer.data());
  }
  std::copy(kNamespaceUrl.begin(), kNamespaceUrl.end(), message);
  std::copy(name.begin(), name.end(), reinterpret_cast<char*>(message + kNamespaceUrl.size()));
  auto digest = sha1(message, kNamespaceUrl.size() + name.size());
  std::array<std::uint8_t, 16> bytes{};
  std::copy_n(digest.begin(), 16, bytes.begin());
  bytes[6] = static_cast<std::uint8_t>((bytes[6] & 0x0F) | 0x50);  // version 5
  bytes[8] = static_cast<std::uint8_t>((bytes[8] & 0x3F) | 0x80);  // RFC 4122 variant
  return bytes;
}

std::string uuid5_url_hex(std::string_view name) {
  const auto bytes = uuid5_url_bytes(name);
  static constexpr char kHex[] = "0123456789abcdef";
  std::string out;
  out.reserve(32);
  for (const auto b : bytes) {
    out += kHex[b >> 4];
    out += kHex[b & 0xF];
  }
  return out;
}

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------
TagBinding user_tag_binding(std::string_view tag, const UserTagOptions& o) {
  TagBinding b;
  b.tag = normalize_tag(tag, true);
  TagProducer producer;
  producer.kind = TagProducerKind::UserOperation;
  producer.node_id = o.node_id;
  TagBindingPolicy policy;
  policy.producer = std::move(producer);
  policy.scope.node_id = o.scope_node_id ? o.scope_node_id : o.node_id;
  policy.scope.output_slot = o.output_slot;
  if (o.target) policy.target = *o.target;
  policy.propagation.topology = o.topology;
  policy.propagation.lineage = o.lineage;
  policy.propagation.explicit_derivations = o.explicit_derivations;
  b.policy = std::move(policy);
  if (o.evidence) {
    b.evidence = *o.evidence;
  } else {
    TagEvidence evidence;
    evidence.kind = TagEvidenceKind::UserAssertion;
    evidence.data.set("authoring_source", "simplecadapi.apply_tag");
    b.evidence = std::move(evidence);
  }
  b.certainty = TagCertainty::Asserted;
  b.lifecycle = TagLifecycle::Assertion;
  b.binding_id = new_binding_id();
  b.validate();
  return b;
}

TagBinding internal_tag_binding(std::string_view tag, const InternalTagOptions& o) {
  // The common case (default rule, no extra evidence) shares its records between all bindings.
  struct Shared {
    Cow<TagBindingPolicy> local, downward;
    Cow<TagEvidence> evidence;
    Shared() {
      TagBindingPolicy p;
      p.producer.kind = TagProducerKind::AutoRule;
      p.producer.rule_id = InternalTagOptions{}.rule_id;
      p.producer.rule_version = InternalTagOptions{}.rule_version;
      p.propagation.lineage = LineagePolicy::None;
      TagBindingPolicy d = p;
      d.propagation.topology = TopologyPropagation::Downward;
      local = std::move(p);
      downward = std::move(d);
      TagEvidence e;
      e.kind = TagEvidenceKind::LegacySnapshot;
      e.data.set("source", "internal_annotation");
      evidence = std::move(e);
    }
  };
  static const Shared shared;
  static const InternalTagOptions defaults;

  TagBinding b;
  b.tag = normalize_tag(tag, true);
  const bool plain = o.rule_id == defaults.rule_id && o.rule_version == defaults.rule_version &&
                     !(o.evidence.is_object() && o.evidence.size() != 0);
  if (plain) {
    b.policy = o.topology == TopologyPropagation::Downward ? shared.downward : shared.local;
    b.evidence = shared.evidence;
  } else {
    TagBindingPolicy policy;
    policy.producer.kind = TagProducerKind::AutoRule;
    policy.producer.rule_id = o.rule_id;
    policy.producer.rule_version = o.rule_version;
    policy.propagation.topology = o.topology;
    policy.propagation.lineage = LineagePolicy::None;
    b.policy = std::move(policy);
    TagEvidence evidence;
    evidence.kind = TagEvidenceKind::LegacySnapshot;
    evidence.data.set("source", "internal_annotation");
    if (o.evidence.is_object())
      for (const auto& [key, value] : o.evidence.as_object()) evidence.data.set(key, value);
    b.evidence = std::move(evidence);
  }
  b.certainty = TagCertainty::Proven;
  b.lifecycle = TagLifecycle::Snapshot;
  b.binding_id = new_binding_id();
  b.validate();
  return b;
}

TagBinding operation_role_tag_binding(std::string_view tag, std::string_view operation, std::string_view role,
                                      std::string_view target_topo_id, std::string_view evidence_method) {
  static constexpr std::string_view kRuleId = "simplecad.operation_output_role";
  static const Cow<TagBindingPolicy> shared = [] {
    TagBindingPolicy p;
    p.producer.kind = TagProducerKind::AutoRule;
    p.producer.rule_id = std::string(kRuleId);
    p.producer.rule_version = "1.0";
    p.propagation.lineage = LineagePolicy::ContinuationFragment;
    return Cow<TagBindingPolicy>(std::move(p));
  }();

  TagBinding b;
  b.tag = normalize_tag(tag, true);
  b.policy = shared;
  TagEvidence evidence;
  evidence.kind = TagEvidenceKind::TopologyChange;
  evidence.data.as_object().reserve(4);
  evidence.data.set("operation", std::string(operation));
  evidence.data.set("result_role", std::string(role));
  evidence.data.set("target_topo_id", std::string(target_topo_id));
  evidence.data.set("evidence_method", std::string(evidence_method));
  b.evidence = std::move(evidence);
  b.certainty = TagCertainty::Proven;
  b.lifecycle = TagLifecycle::Recompute;
  std::string key;
  for (const auto part : {kRuleId, operation, role, target_topo_id, b.tag.view()}) {
    if (!key.empty()) key += '|';
    key.append(part);
  }
  b.binding_id = deterministic_binding_id(key);
  b.validate();
  return b;
}

TagBinding projected_tag_binding(const TagBinding& source, std::string_view operation, std::string_view role,
                                 std::string_view source_topo_id, std::string_view target_topo_id,
                                 std::string_view evidence_method, TopologyPropagation topology) {
  static constexpr std::string_view kRuleId = "simplecad.feature_source_tag_projection";
  const Value& src = source.evidence->data;

  auto lookup = [&](std::string_view key) -> const Value* { return src.find(key); };
  const Value* root_binding = lookup("source_binding_id");
  const std::string root_binding_id = root_binding != nullptr ? value_text(*root_binding) : source.binding_id.str();
  const Value* root_topo = lookup("source_topo_id");
  const std::string root_topo_id = root_topo != nullptr ? value_text(*root_topo) : std::string(source_topo_id);

  const Value* output_role = lookup("source_operation_output_role");
  if (output_role == nullptr) output_role = lookup("operation_output_role");
  const Value* topology_name = lookup("source_topology_name");
  if (topology_name == nullptr) topology_name = lookup("topology_name");

  // One policy per (topology, lineage) pair: the producer is always the projection rule.
  static const std::array<Cow<TagBindingPolicy>, 2 * 4> shared = [] {
    std::array<Cow<TagBindingPolicy>, 2 * 4> all;
    for (int t = 0; t < 2; ++t)
      for (int l = 0; l < 4; ++l) {
        TagBindingPolicy p;
        p.producer.kind = TagProducerKind::AutoRule;
        p.producer.rule_id = std::string(kRuleId);
        p.producer.rule_version = "1.0";
        p.propagation.topology = static_cast<TopologyPropagation>(t);
        p.propagation.lineage = static_cast<LineagePolicy>(l);
        all[static_cast<std::size_t>(t * 4 + l)] = std::move(p);
      }
    return all;
  }();

  TagBinding b;
  b.tag = source.tag;
  if (source.propagation().explicit_derivations.empty()) {
    b.policy = shared[static_cast<std::size_t>(static_cast<int>(topology) * 4 + static_cast<int>(source.propagation().lineage))];
  } else {
    TagBindingPolicy policy = *shared[0];
    policy.propagation.topology = topology;
    policy.propagation.lineage = source.propagation().lineage;
    policy.propagation.explicit_derivations = source.propagation().explicit_derivations;
    b.policy = std::move(policy);
  }
  TagEvidence evidence;
  evidence.kind = TagEvidenceKind::TopologyChange;
  evidence.data.set("operation", std::string(operation));
  evidence.data.set("result_role", std::string(role));
  evidence.data.set("source_binding_id", root_binding_id);
  evidence.data.set("source_topo_id", root_topo_id);
  evidence.data.set("target_topo_id", std::string(target_topo_id));
  evidence.data.set("evidence_method", std::string(evidence_method));
  if (output_role != nullptr && output_role->is_object()) evidence.data.set("source_operation_output_role", *output_role);
  if (topology_name != nullptr && topology_name->is_object()) evidence.data.set("source_topology_name", *topology_name);
  b.evidence = std::move(evidence);
  b.certainty = TagCertainty::Proven;
  b.lifecycle = TagLifecycle::Recompute;

  std::string key;
  for (const auto part : {kRuleId, std::string_view(root_binding_id), operation, role, std::string_view(root_topo_id),
                          target_topo_id}) {
    if (!key.empty()) key += '|';
    key.append(part);
  }
  b.binding_id = deterministic_binding_id(key);
  b.validate();
  return b;
}

TagBinding legacy_tag_binding(std::string_view tag, std::optional<std::string_view> diagnostic) {
  TagBinding b;
  b.tag = normalize_tag(tag, true);
  TagProducer producer;
  producer.kind = TagProducerKind::LegacyImport;
  b.policy.mut().producer = std::move(producer);
  TagTarget target;
  target.kind = TagTargetKind::LegacyEffective;
  b.policy.mut().target = std::move(target);
  b.attachment = TagAttachment::EffectiveLegacy;
  TagPropagation propagation;
  propagation.topology = TopologyPropagation::Local;
  propagation.lineage = LineagePolicy::None;
  b.policy.mut().propagation = std::move(propagation);
  TagEvidence evidence;
  evidence.kind = TagEvidenceKind::LegacySnapshot;
  Value imported = Value::array();
  imported.push_back(std::string(tag));
  evidence.data.set("imported_tags", std::move(imported));
  if (diagnostic) evidence.data.set("migration_diagnostic", std::string(*diagnostic));
  b.evidence = std::move(evidence);
  b.certainty = TagCertainty::Asserted;
  b.lifecycle = TagLifecycle::Snapshot;
  b.binding_id = new_binding_id();
  b.validate();
  return b;
}

// ---------------------------------------------------------------------------
// Lineage rules
// ---------------------------------------------------------------------------
bool lineage_policy_allows(LineagePolicy policy, LineageDerivation derivation) {
  switch (policy) {
    case LineagePolicy::None: return false;
    case LineagePolicy::Continuation: return derivation == LineageDerivation::Continuation;
    case LineagePolicy::ContinuationFragment:
      return derivation == LineageDerivation::Continuation || derivation == LineageDerivation::Fragment;
    case LineagePolicy::Explicit: return false;  // needs the propagation record
  }
  return false;
}

bool lineage_policy_allows(const TagPropagation& propagation, LineageDerivation derivation) {
  if (propagation.lineage == LineagePolicy::Explicit) {
    return std::find(propagation.explicit_derivations.begin(), propagation.explicit_derivations.end(), derivation) !=
           propagation.explicit_derivations.end();
  }
  return lineage_policy_allows(propagation.lineage, derivation);
}

// ---------------------------------------------------------------------------
// Tag policy and anchors
// ---------------------------------------------------------------------------
bool TagPolicy::should_propagate(std::string_view tag) const {
  if (contains(block_exact, tag)) return false;
  for (const auto& prefix : block_prefixes)
    if (starts_with(tag, prefix)) return false;
  if (contains(propagate_exact, tag)) return true;
  for (const auto& prefix : propagate_prefixes)
    if (starts_with(tag, prefix)) return true;
  return false;
}

const TagPolicy& default_tag_policy() {
  static const TagPolicy policy;
  return policy;
}

std::vector<std::string> resolve_anchor_tag_candidates(std::string_view tag) {
  const std::string token = lower(strip(tag));
  if (token.empty()) return {};

  static constexpr std::string_view kTopologyPrefixes[] = {"face.", "edge.", "wire.", "vertex.", "solid."};
  auto expand = [&](const std::string& bare) {
    std::vector<std::string> out{"role." + bare, "anchor." + bare};
    for (const auto prefix : kTopologyPrefixes) out.push_back(std::string(prefix) + bare);
    out.push_back("legacy." + bare);
    out.push_back(bare);
    return out;
  };

  if (is_normalized_tag(token) && token.find('.') != std::string::npos) {
    if (starts_with(token, "role.")) return expand(token.substr(5));
    if (starts_with(token, "anchor.")) return expand(token.substr(7));
    for (const auto prefix : kTopologyPrefixes)
      if (starts_with(token, prefix)) return expand(token.substr(token.find('.') + 1));
    if (starts_with(token, "legacy.")) return expand(token.substr(7));
    return {token};
  }
  return expand(token);
}

// ---------------------------------------------------------------------------
// Wire format
// ---------------------------------------------------------------------------
namespace {

void strict_mapping(std::string_view name, const Value& data, std::initializer_list<std::string_view> required,
                    std::initializer_list<std::string_view> optional = {}) {
  if (!data.is_object()) throw TagValidationError(std::string(name) + " must be an object");
  std::set<std::string> missing, unknown;
  for (const auto key : required)
    if (data.find(key) == nullptr) missing.insert(std::string(key));
  for (const auto& [key, ignored] : data.as_object()) {
    (void)ignored;
    const bool known = std::find(required.begin(), required.end(), key) != required.end() ||
                       std::find(optional.begin(), optional.end(), key) != optional.end();
    if (!known) unknown.insert(key);
  }
  auto join = [](const std::set<std::string>& items) {
    std::string out;
    for (const auto& item : items) out += (out.empty() ? "" : ", ") + item;
    return out;
  };
  if (!missing.empty()) throw TagValidationError(std::string(name) + " is missing required field(s): " + join(missing));
  if (!unknown.empty()) throw TagValidationError(std::string(name) + " contains unknown field(s): " + join(unknown));
}

std::optional<std::string> optional_string(const Value& value, std::string_view field) {
  if (value.is_null()) return std::nullopt;
  if (!value.is_string() || value.as_string().empty())
    throw TagValidationError(std::string(field) + " must be null or a non-empty string");
  return value.as_string();
}

const std::string& require_string(const Value& value, std::string_view field) {
  if (!value.is_string()) throw TagValidationError(std::string(field) + " must be a string");
  return value.as_string();
}

// TagTarget's own consistency rules live in TagBinding::validate; run them on a
// probe binding that is otherwise valid.
void validate_target_alone(const TagTarget& target) {
  TagBinding probe;
  probe.tag = "probe.target";
  probe.binding_id = "probe";
  probe.policy.mut().target = target;
  if (target.kind == TagTargetKind::LegacyEffective) {
    probe.attachment = TagAttachment::EffectiveLegacy;
    probe.policy.mut().producer.kind = TagProducerKind::LegacyImport;
    probe.policy.mut().propagation.lineage = LineagePolicy::None;
    probe.lifecycle = TagLifecycle::Snapshot;
    probe.evidence.mut().kind = TagEvidenceKind::LegacySnapshot;
  }
  probe.validate();
}

}  // namespace

TagBindingScope tag_binding_scope_from_value(const Value& value) {
  strict_mapping("TagBinding.scope", value, {"node_id", "output_slot"});
  TagBindingScope scope;
  scope.node_id = optional_string(*value.find("node_id"), "scope.node_id");
  const Value& slot = *value.find("output_slot");
  if (slot.is_bool() || !slot.is_int()) throw TagValidationError("scope.output_slot must be an integer");
  if (slot.as_int() < 0) throw TagValidationError("scope.output_slot must be >= 0");
  scope.output_slot = static_cast<int>(slot.as_int());
  return scope;
}

TagProducer tag_producer_from_value(const Value& value) {
  strict_mapping("TagBinding.producer", value, {"kind", "node_id", "rule_id", "rule_version"});
  TagProducer producer;
  producer.kind = parse_tag_producer_kind(require_string(*value.find("kind"), "producer kind"));
  producer.node_id = optional_string(*value.find("node_id"), "producer.node_id");
  producer.rule_id = optional_string(*value.find("rule_id"), "producer.rule_id");
  producer.rule_version = optional_string(*value.find("rule_version"), "producer.rule_version");
  const bool auto_rule = producer.kind == TagProducerKind::AutoRule;
  if (auto_rule && (!producer.rule_id || !producer.rule_version))
    throw TagValidationError("auto_rule producers require rule_id and rule_version");
  if (!auto_rule && (producer.rule_id || producer.rule_version))
    throw TagValidationError("rule_id and rule_version are only valid for auto_rule producers");
  return producer;
}

TagTarget tag_target_from_value(const Value& value) {
  if (!value.is_object()) throw TagValidationError("TagBinding.target must be an object");
  strict_mapping("TagBinding.target", value, {"kind"}, {"query_hash", "binding_hash", "selector", "refs"});
  TagTarget target;
  target.kind = parse_tag_target_kind(require_string(*value.find("kind"), "target kind"));
  if (const Value* v = value.find("query_hash")) target.query_hash = optional_string(*v, "target.query_hash");
  if (const Value* v = value.find("binding_hash")) target.binding_hash = optional_string(*v, "target.binding_hash");
  if (const Value* v = value.find("selector"); v != nullptr && !v->is_null()) {
    if (!v->is_object()) throw TagValidationError("target.selector must be an object");
    target.selector = *v;
  }
  if (const Value* v = value.find("refs")) {
    if (!v->is_array()) throw TagValidationError("target.refs must be an array of objects");
    for (const auto& ref : v->as_array()) {
      if (!ref.is_object()) throw TagValidationError("target.refs must be an array of objects");
      target.refs.push_back(ref);
    }
  }
  validate_target_alone(target);
  return target;
}

TagPropagation tag_propagation_from_value(const Value& value) {
  strict_mapping("TagBinding.propagation", value, {"topology", "lineage"}, {"derivations"});
  TagPropagation p;
  p.topology = parse_topology_propagation(require_string(*value.find("topology"), "topology propagation"));
  p.lineage = parse_lineage_policy(require_string(*value.find("lineage"), "lineage policy"));
  if (const Value* v = value.find("derivations")) {
    if (!v->is_array()) throw TagValidationError("propagation.derivations must be an array");
    for (const auto& item : v->as_array())
      p.explicit_derivations.push_back(parse_lineage_derivation(require_string(item, "lineage derivation")));
  }
  if (p.lineage == LineagePolicy::Explicit && p.explicit_derivations.empty())
    throw TagValidationError("explicit lineage policy requires explicit_derivations");
  if (p.lineage != LineagePolicy::Explicit && !p.explicit_derivations.empty())
    throw TagValidationError("explicit_derivations are only valid with explicit lineage policy");
  return p;
}

TagEvidence tag_evidence_from_value(const Value& value) {
  if (!value.is_object()) throw TagValidationError("TagBinding.evidence must be an object");
  const Value* kind = value.find("kind");
  if (kind == nullptr) throw TagValidationError("TagBinding.evidence is missing required field: kind");
  TagEvidence evidence;
  evidence.kind = parse_tag_evidence_kind(require_string(*kind, "evidence kind"));
  for (const auto& [key, item] : value.as_object())
    if (key != "kind") evidence.data.set(key, item);
  return evidence;
}

TagBinding tag_binding_from_value(const Value& value) {
  strict_mapping("TagBinding", value,
                 {"schema_version", "binding_id", "tag", "producer", "scope", "target", "attachment", "propagation",
                  "evidence", "certainty", "lifecycle"});
  TagBinding b;
  b.policy.mut().schema_version = require_string(*value.find("schema_version"), "schema_version");
  b.binding_id = require_string(*value.find("binding_id"), "binding_id");
  const std::string raw_tag = require_string(*value.find("tag"), "tag");
  b.policy.mut().producer = tag_producer_from_value(*value.find("producer"));
  b.policy.mut().scope = tag_binding_scope_from_value(*value.find("scope"));
  b.policy.mut().target = tag_target_from_value(*value.find("target"));
  b.attachment = parse_tag_attachment(require_string(*value.find("attachment"), "attachment"));
  b.policy.mut().propagation = tag_propagation_from_value(*value.find("propagation"));
  b.evidence = tag_evidence_from_value(*value.find("evidence"));
  b.certainty = parse_tag_certainty(require_string(*value.find("certainty"), "certainty"));
  b.lifecycle = parse_tag_lifecycle(require_string(*value.find("lifecycle"), "lifecycle"));
  b.tag = normalize_tag(raw_tag, true);
  b.validate();
  return b;
}

TagLineageWitness tag_lineage_witness_from_value(const Value& value) {
  strict_mapping("TagLineageWitness", value,
                 {"binding", "derivation", "source_topo_id", "target_topo_id", "evidence", "coverage"});
  TagLineageWitness w;
  w.binding = tag_binding_from_value(*value.find("binding"));
  w.derivation = parse_lineage_derivation(require_string(*value.find("derivation"), "lineage derivation"));
  w.source_topo_id = require_string(*value.find("source_topo_id"), "source_topo_id");
  w.target_topo_id = require_string(*value.find("target_topo_id"), "target_topo_id");
  w.evidence = tag_evidence_from_value(*value.find("evidence"));
  w.coverage = require_string(*value.find("coverage"), "coverage");
  w.validate();
  return w;
}

// ---------------------------------------------------------------------------
// Equality
// ---------------------------------------------------------------------------
bool operator==(const TagProducer& a, const TagProducer& b) {
  return a.kind == b.kind && a.node_id == b.node_id && a.rule_id == b.rule_id && a.rule_version == b.rule_version;
}

bool operator==(const TagBinding& a, const TagBinding& b) { return a.to_value() == b.to_value(); }

bool operator==(const TagLineageWitness& a, const TagLineageWitness& b) { return a.to_value() == b.to_value(); }

}  // namespace scad
