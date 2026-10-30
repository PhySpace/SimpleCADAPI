// The tag data model: Semantic Binding Schema 1.0.
//
// Port of the dataclasses in simplecadapi/topology/tagging.py.  A TagBinding is
// the canonical record of "this tag was asserted on this entity, by this
// producer, with this evidence"; the plain tag-name set a shape shows is a
// cache computed from its bindings.  Validation lives in the factory functions
// and in TagBinding::validate(), so an invalid binding cannot be stored.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/cow.hpp"
#include "scad/core/symbol.hpp"
#include "scad/core/value.hpp"
#include "scad/topo/binding_id.hpp"

namespace scad {

inline constexpr std::string_view kTagBindingSchemaVersion = "1.0";

// ---------------------------------------------------------------------------
// Enums.  Each has a stable wire string (to_string / parse_*) used by the
// serialized form and by the Python layer.
// ---------------------------------------------------------------------------
enum class TagScope { Local, Inherited, Effective, Lineage };
enum class TopologyPropagation { Local, Downward };
enum class LineagePolicy { None, Continuation, ContinuationFragment, Explicit };
enum class LineageDerivation { Continuation, Fragment, Merge, Intersection, Boundary, Replacement };
enum class TagAttachment : std::uint8_t { Local, Inherited, EffectiveLegacy };
enum class TagProducerKind { UserOperation, AutoRule, ImportedSidecar, LegacyImport };
enum class TagTargetKind { SelectionQuery, ScopeRoot, ExplicitRefs, LegacyEffective };
enum class TagEvidenceKind {
  UserAssertion,
  QueryExecution,
  TopologyChange,
  GeometryClassification,
  ImportedSidecar,
  LegacySnapshot
};
enum class TagCertainty : std::uint8_t { Asserted, Proven };
enum class TagLifecycle : std::uint8_t { Assertion, Recompute, Snapshot };

std::string_view to_string(TagScope v) noexcept;
std::string_view to_string(TopologyPropagation v) noexcept;
std::string_view to_string(LineagePolicy v) noexcept;
std::string_view to_string(LineageDerivation v) noexcept;
std::string_view to_string(TagAttachment v) noexcept;
std::string_view to_string(TagProducerKind v) noexcept;
std::string_view to_string(TagTargetKind v) noexcept;
std::string_view to_string(TagEvidenceKind v) noexcept;
std::string_view to_string(TagCertainty v) noexcept;
std::string_view to_string(TagLifecycle v) noexcept;

// parse_*: throw scad::TagValidationError on an unknown string.
TagScope parse_tag_scope(std::string_view s);
TopologyPropagation parse_topology_propagation(std::string_view s);
LineagePolicy parse_lineage_policy(std::string_view s);
LineageDerivation parse_lineage_derivation(std::string_view s);
TagAttachment parse_tag_attachment(std::string_view s);
TagProducerKind parse_tag_producer_kind(std::string_view s);
TagTargetKind parse_tag_target_kind(std::string_view s);
TagEvidenceKind parse_tag_evidence_kind(std::string_view s);
TagCertainty parse_tag_certainty(std::string_view s);
TagLifecycle parse_tag_lifecycle(std::string_view s);

// ---------------------------------------------------------------------------
// Records.
// ---------------------------------------------------------------------------
struct TagBindingScope {
  std::optional<std::string> node_id;
  int output_slot = 0;
  Value to_value() const;
};

struct TagProducer {
  TagProducerKind kind = TagProducerKind::UserOperation;
  std::optional<std::string> node_id;
  std::optional<std::string> rule_id;  // required (with rule_version) for AutoRule only
  std::optional<std::string> rule_version;
  Value to_value() const;
};

struct TagTarget {
  TagTargetKind kind = TagTargetKind::ScopeRoot;
  std::optional<std::string> query_hash;
  std::optional<std::string> binding_hash;
  std::optional<Value> selector;  // object
  std::vector<Value> refs;        // objects
  Value to_value() const;
};

struct TagPropagation {
  TopologyPropagation topology = TopologyPropagation::Local;
  LineagePolicy lineage = LineagePolicy::ContinuationFragment;
  std::vector<LineageDerivation> explicit_derivations;  // only with LineagePolicy::Explicit
  Value to_value() const;
};

struct TagEvidence {
  TagEvidenceKind kind = TagEvidenceKind::UserAssertion;
  Value data = Value::object();  // never contains "kind"
  Value to_value() const;
};

// What a binding says about itself besides its tag, id and evidence: who made it, in which
// scope, aimed at what, propagated how.  Bindings made by the same rule share one record.
struct TagBindingPolicy {
  TagProducer producer;
  TagBindingScope scope;
  TagTarget target;
  TagPropagation propagation;
  Symbol schema_version{kTagBindingSchemaVersion};
};

// Compact by construction: the tag name is an interned symbol, the id is 128 bits, and the policy
// and the evidence are shared (Cow) among bindings that are alike, so a binding is 64 bytes plus
// whatever evidence is its own.  Reading (`b.producer()`, `b.evidence->kind`) never copies;
// writing goes through `b.policy.mut()` / `b.evidence.mut()`.
struct TagBinding {
  Symbol tag;  // normalized
  BindingId binding_id;
  Cow<TagBindingPolicy> policy;
  Cow<TagEvidence> evidence;
  TagAttachment attachment = TagAttachment::Local;
  TagCertainty certainty = TagCertainty::Asserted;
  TagLifecycle lifecycle = TagLifecycle::Assertion;

  const TagProducer& producer() const noexcept { return policy->producer; }
  const TagBindingScope& scope() const noexcept { return policy->scope; }
  const TagTarget& target() const noexcept { return policy->target; }
  const TagPropagation& propagation() const noexcept { return policy->propagation; }
  Symbol schema_version() const noexcept { return policy->schema_version; }

  // Throws TagValidationError when the combination of fields is not allowed
  // (the rules enforced by TagBinding.__post_init__).
  void validate() const;
  Value to_value() const;
};

struct TagLineageWitness {
  TagBinding binding;
  LineageDerivation derivation = LineageDerivation::Continuation;
  std::string source_topo_id;
  std::string target_topo_id;
  Cow<TagEvidence> evidence;
  std::string coverage{"complete"};  // complete | partial | none

  void validate() const;
  Value to_value() const;
};

// A binding a shape inherits from an ancestor, with the containment path that
// carries it: {ancestor id, ..., this shape's id}.
struct InheritedTagBinding {
  TagBinding binding;
  std::vector<std::string> path;
};

// ---------------------------------------------------------------------------
// Tag names.
// ---------------------------------------------------------------------------

// A tag is dot-separated segments, each [a-z][a-z0-9_-]*.
bool is_normalized_tag(std::string_view tag) noexcept;
// strict: throw TagValidationError when the tag is not already a valid name.
// Non-strict: lower-case and replace separators first, then validate.
std::string normalize_tag(std::string_view tag, bool strict = true);
TagScope normalize_tag_scope(std::string_view scope);

// A fresh "tag_binding_<uuid4 hex>" id.
BindingId new_binding_id();

}  // namespace scad
