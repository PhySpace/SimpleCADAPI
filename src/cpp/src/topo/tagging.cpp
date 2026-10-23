#include "scad/topo/tagging.hpp"

#include <algorithm>
#include <cctype>
#include <random>

#include "scad/core/error.hpp"

namespace scad {

namespace {

template <class E, std::size_t N>
std::string_view lookup(E v, const std::pair<E, std::string_view> (&table)[N]) noexcept {
  for (const auto& [key, text] : table)
    if (key == v) return text;
  return "";
}

template <class E, std::size_t N>
E parse_enum(std::string_view s, const std::pair<E, std::string_view> (&table)[N], const char* what) {
  for (const auto& [key, text] : table)
    if (text == s) return key;
  throw TagValidationError(std::string("unknown ") + what + " '" + std::string(s) + "'");
}

using std::pair;
constexpr pair<TagScope, std::string_view> kScope[] = {
    {TagScope::Local, "local"}, {TagScope::Inherited, "inherited"},
    {TagScope::Effective, "effective"}, {TagScope::Lineage, "lineage"}};
constexpr pair<TopologyPropagation, std::string_view> kTopo[] = {
    {TopologyPropagation::Local, "local"}, {TopologyPropagation::Downward, "downward"}};
constexpr pair<LineagePolicy, std::string_view> kPolicy[] = {
    {LineagePolicy::None, "none"},
    {LineagePolicy::Continuation, "continuation"},
    {LineagePolicy::ContinuationFragment, "continuation_fragment"},
    {LineagePolicy::Explicit, "explicit"}};
constexpr pair<LineageDerivation, std::string_view> kDerivation[] = {
    {LineageDerivation::Continuation, "continuation"}, {LineageDerivation::Fragment, "fragment"},
    {LineageDerivation::Merge, "merge"},               {LineageDerivation::Intersection, "intersection"},
    {LineageDerivation::Boundary, "boundary"},         {LineageDerivation::Replacement, "replacement"}};
constexpr pair<TagAttachment, std::string_view> kAttachment[] = {
    {TagAttachment::Local, "local"},
    {TagAttachment::Inherited, "inherited"},
    {TagAttachment::EffectiveLegacy, "effective_legacy"}};
constexpr pair<TagProducerKind, std::string_view> kProducer[] = {
    {TagProducerKind::UserOperation, "user_operation"}, {TagProducerKind::AutoRule, "auto_rule"},
    {TagProducerKind::ImportedSidecar, "imported_sidecar"}, {TagProducerKind::LegacyImport, "legacy_import"}};
constexpr pair<TagTargetKind, std::string_view> kTarget[] = {
    {TagTargetKind::SelectionQuery, "selection_query"}, {TagTargetKind::ScopeRoot, "scope_root"},
    {TagTargetKind::ExplicitRefs, "explicit_refs"}, {TagTargetKind::LegacyEffective, "legacy_effective"}};
constexpr pair<TagEvidenceKind, std::string_view> kEvidence[] = {
    {TagEvidenceKind::UserAssertion, "user_assertion"},
    {TagEvidenceKind::QueryExecution, "query_execution"},
    {TagEvidenceKind::TopologyChange, "topology_change"},
    {TagEvidenceKind::GeometryClassification, "geometry_classification"},
    {TagEvidenceKind::ImportedSidecar, "imported_sidecar"},
    {TagEvidenceKind::LegacySnapshot, "legacy_snapshot"}};
constexpr pair<TagCertainty, std::string_view> kCertainty[] = {
    {TagCertainty::Asserted, "asserted"}, {TagCertainty::Proven, "proven"}};
constexpr pair<TagLifecycle, std::string_view> kLifecycle[] = {
    {TagLifecycle::Assertion, "assertion"}, {TagLifecycle::Recompute, "recompute"},
    {TagLifecycle::Snapshot, "snapshot"}};

Value optional_string(const std::optional<std::string>& s) { return s ? Value(*s) : Value(); }

bool is_segment_start(char c) { return c >= 'a' && c <= 'z'; }
bool is_segment_char(char c) {
  return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-';
}

std::string trim(std::string_view s) {
  const auto b = s.find_first_not_of(" \t\r\n\f\v");
  if (b == std::string_view::npos) return {};
  const auto e = s.find_last_not_of(" \t\r\n\f\v");
  return std::string(s.substr(b, e - b + 1));
}

}  // namespace

std::string_view to_string(TagScope v) noexcept { return lookup(v, kScope); }
std::string_view to_string(TopologyPropagation v) noexcept { return lookup(v, kTopo); }
std::string_view to_string(LineagePolicy v) noexcept { return lookup(v, kPolicy); }
std::string_view to_string(LineageDerivation v) noexcept { return lookup(v, kDerivation); }
std::string_view to_string(TagAttachment v) noexcept { return lookup(v, kAttachment); }
std::string_view to_string(TagProducerKind v) noexcept { return lookup(v, kProducer); }
std::string_view to_string(TagTargetKind v) noexcept { return lookup(v, kTarget); }
std::string_view to_string(TagEvidenceKind v) noexcept { return lookup(v, kEvidence); }
std::string_view to_string(TagCertainty v) noexcept { return lookup(v, kCertainty); }
std::string_view to_string(TagLifecycle v) noexcept { return lookup(v, kLifecycle); }

TagScope parse_tag_scope(std::string_view s) { return parse_enum(s, kScope, "tag scope"); }
TopologyPropagation parse_topology_propagation(std::string_view s) { return parse_enum(s, kTopo, "topology propagation"); }
LineagePolicy parse_lineage_policy(std::string_view s) { return parse_enum(s, kPolicy, "lineage policy"); }
LineageDerivation parse_lineage_derivation(std::string_view s) { return parse_enum(s, kDerivation, "lineage derivation"); }
TagAttachment parse_tag_attachment(std::string_view s) { return parse_enum(s, kAttachment, "attachment"); }
TagProducerKind parse_tag_producer_kind(std::string_view s) { return parse_enum(s, kProducer, "producer kind"); }
TagTargetKind parse_tag_target_kind(std::string_view s) { return parse_enum(s, kTarget, "target kind"); }
TagEvidenceKind parse_tag_evidence_kind(std::string_view s) { return parse_enum(s, kEvidence, "evidence kind"); }
TagCertainty parse_tag_certainty(std::string_view s) { return parse_enum(s, kCertainty, "certainty"); }
TagLifecycle parse_tag_lifecycle(std::string_view s) { return parse_enum(s, kLifecycle, "lifecycle"); }

// ---------------------------------------------------------------------------
// to_value
// ---------------------------------------------------------------------------
Value TagBindingScope::to_value() const {
  Value v = Value::object();
  v.set("node_id", optional_string(node_id));
  v.set("output_slot", output_slot);
  return v;
}

Value TagProducer::to_value() const {
  Value v = Value::object();
  v.set("kind", std::string(to_string(kind)));
  v.set("node_id", optional_string(node_id));
  v.set("rule_id", optional_string(rule_id));
  v.set("rule_version", optional_string(rule_version));
  return v;
}

Value TagTarget::to_value() const {
  Value v = Value::object();
  v.set("kind", std::string(to_string(kind)));
  if (query_hash) {
    v.set("query_hash", *query_hash);
    v.set("binding_hash", optional_string(binding_hash));
  }
  if (selector) v.set("selector", *selector);
  if (!refs.empty()) v.set("refs", Value(Value::Array(refs.begin(), refs.end())));
  return v;
}

Value TagPropagation::to_value() const {
  Value v = Value::object();
  v.set("topology", std::string(to_string(topology)));
  v.set("lineage", std::string(to_string(lineage)));
  if (!explicit_derivations.empty()) {
    Value::Array items;
    for (const auto d : explicit_derivations) items.emplace_back(std::string(to_string(d)));
    v.set("derivations", Value(std::move(items)));
  }
  return v;
}

Value TagEvidence::to_value() const {
  Value v = Value::object();
  v.set("kind", std::string(to_string(kind)));
  if (data.is_object())
    for (const auto& [key, item] : data.as_object()) v.set(key, item);
  return v;
}

Value TagBinding::to_value() const {
  Value v = Value::object();
  v.set("schema_version", schema_version().str());
  v.set("binding_id", binding_id.str());
  v.set("tag", tag.str());
  v.set("producer", producer().to_value());
  v.set("scope", scope().to_value());
  v.set("target", target().to_value());
  v.set("attachment", std::string(to_string(attachment)));
  v.set("propagation", propagation().to_value());
  v.set("evidence", evidence->to_value());
  v.set("certainty", std::string(to_string(certainty)));
  v.set("lifecycle", std::string(to_string(lifecycle)));
  return v;
}

Value TagLineageWitness::to_value() const {
  Value v = Value::object();
  v.set("binding", binding.to_value());
  v.set("derivation", std::string(to_string(derivation)));
  v.set("source_topo_id", source_topo_id);
  v.set("target_topo_id", target_topo_id);
  v.set("evidence", evidence->to_value());
  v.set("coverage", coverage);
  return v;
}

// ---------------------------------------------------------------------------
// validate: the rules TagBinding.__post_init__ enforces.
// ---------------------------------------------------------------------------
namespace {

void validate_producer(const TagProducer& p) {
  const bool auto_rule = p.kind == TagProducerKind::AutoRule;
  if (auto_rule && (!p.rule_id || !p.rule_version))
    throw TagValidationError("auto_rule producers require rule_id and rule_version");
  if (!auto_rule && (p.rule_id || p.rule_version))
    throw TagValidationError("rule_id and rule_version are only valid for auto_rule producers");
}

void validate_propagation(const TagPropagation& p) {
  if (p.lineage == LineagePolicy::Explicit && p.explicit_derivations.empty())
    throw TagValidationError("explicit lineage policy requires explicit_derivations");
  if (p.lineage != LineagePolicy::Explicit && !p.explicit_derivations.empty())
    throw TagValidationError("explicit_derivations are only valid with explicit lineage policy");
}

void validate_target(const TagTarget& t) {
  const bool query_fields = t.query_hash || t.binding_hash || t.selector;
  switch (t.kind) {
    case TagTargetKind::SelectionQuery:
      if (!t.selector && !t.query_hash)
        throw TagValidationError("selection_query targets require selector or query_hash");
      if (t.query_hash.has_value() != t.binding_hash.has_value())
        throw TagValidationError("selection_query query_hash and binding_hash must be provided together");
      if (!t.refs.empty())
        throw TagValidationError("selection_query target refs belong in execution evidence");
      break;
    case TagTargetKind::ExplicitRefs:
      if (t.refs.empty()) throw TagValidationError("explicit_refs targets require refs");
      if (query_fields) throw TagValidationError("explicit_refs targets cannot contain query fields");
      break;
    case TagTargetKind::LegacyEffective:
      if (query_fields) throw TagValidationError("legacy_effective targets cannot contain query fields");
      break;
    case TagTargetKind::ScopeRoot:
      if (query_fields || !t.refs.empty())
        throw TagValidationError("scope_root targets cannot contain query fields or refs");
      break;
  }
}

}  // namespace

void TagBinding::validate() const {
  if (!is_normalized_tag(tag.view())) throw TagValidationError("tag '" + tag.str() + "' is not normalized");
  validate_producer(producer());
  validate_propagation(propagation());
  validate_target(target());
  if (scope().output_slot < 0) throw TagValidationError("scope.output_slot must be >= 0");
  if (evidence->data.is_object() && evidence->data.find("kind"))
    throw TagValidationError("evidence data cannot redefine kind");
  if (schema_version() != kTagBindingSchemaVersion)
    throw TagValidationError("unsupported TagBinding schema_version '" + schema_version().str() + "'");
  if (binding_id.empty()) throw TagValidationError("binding_id must be a non-empty string");
  if (attachment == TagAttachment::Inherited)
    throw TagValidationError("inherited is a computed attachment and cannot be stored in TagBinding");
  if (attachment == TagAttachment::EffectiveLegacy) {
    if (producer().kind != TagProducerKind::LegacyImport)
      throw TagValidationError("effective_legacy bindings require a legacy_import producer");
    if (target().kind != TagTargetKind::LegacyEffective)
      throw TagValidationError("effective_legacy bindings require a legacy_effective target");
    if (propagation().lineage != LineagePolicy::None)
      throw TagValidationError("legacy effective bindings cannot claim lineage");
    if (lifecycle != TagLifecycle::Snapshot)
      throw TagValidationError("legacy effective bindings require snapshot lifecycle");
    if (evidence->kind != TagEvidenceKind::LegacySnapshot)
      throw TagValidationError("legacy effective bindings require legacy_snapshot evidence");
  } else if (target().kind == TagTargetKind::LegacyEffective) {
    throw TagValidationError("legacy_effective targets require effective_legacy attachment");
  }
}

void TagLineageWitness::validate() const {
  binding.validate();
  if (source_topo_id.empty()) throw TagValidationError("source_topo_id must be a non-empty string");
  if (target_topo_id.empty()) throw TagValidationError("target_topo_id must be a non-empty string");
  if (coverage != "complete" && coverage != "partial" && coverage != "none")
    throw TagValidationError("lineage witness coverage must be complete, partial, or none");
}

// ---------------------------------------------------------------------------
// Names.
// ---------------------------------------------------------------------------
bool is_normalized_tag(std::string_view tag) noexcept {
  if (tag.empty()) return false;
  bool at_start = true;
  for (const char c : tag) {
    if (at_start) {
      if (!is_segment_start(c)) return false;
      at_start = false;
    } else if (c == '.') {
      at_start = true;
    } else if (!is_segment_char(c)) {
      return false;
    }
  }
  return !at_start;  // must not end on a dot
}

std::string normalize_tag(std::string_view tag, bool strict) {
  std::string cleaned = trim(tag);
  if (strict) {
    if (!is_normalized_tag(cleaned)) throw ValueError("tag '" + std::string(tag) + "' is not normalized");
    return cleaned;
  }
  std::string lowered;
  lowered.reserve(cleaned.size());
  bool in_space = false;
  for (const char raw : cleaned) {
    const auto c = static_cast<unsigned char>(raw);
    if (std::isspace(c)) {
      if (!in_space) lowered += '_';
      in_space = true;
      continue;
    }
    in_space = false;
    if (raw == ':') lowered += '_';
    else if (raw == '/') lowered += '.';
    else lowered += static_cast<char>(std::tolower(c));
  }
  if (!is_normalized_tag(lowered)) throw ValueError("tag '" + std::string(tag) + "' cannot be normalized");
  return lowered;
}

TagScope normalize_tag_scope(std::string_view scope) {
  std::string lowered = trim(scope);
  std::transform(lowered.begin(), lowered.end(), lowered.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  for (const auto& [key, text] : kScope)
    if (text == lowered) return key;
  throw ValueError("unsupported tag scope '" + std::string(scope) +
                   "'; expected one of: effective, inherited, lineage, local");
}

BindingId new_binding_id() {
  // 128 random bits, like uuid4().hex; thread_local keeps this lock-free.
  thread_local std::mt19937_64 rng{std::random_device{}()};
  const std::uint64_t hi = rng();
  return BindingId::from_words(hi, rng());
}

}  // namespace scad
