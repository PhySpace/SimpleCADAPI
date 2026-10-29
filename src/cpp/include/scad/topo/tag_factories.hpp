// Binding factories, tag policy, lineage rules and the strict wire format of the
// tag data model: the rest of simplecadapi/topology/tagging.py.
//
// tagging.hpp holds the records; this header builds them.  It lives in topo
// because Shape itself needs internal_tag_binding.
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/topo/tagging.hpp"

namespace scad {

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

struct UserTagOptions {
  std::optional<std::string> node_id;  // producer.node_id; also scope.node_id unless scope_node_id is set
  std::optional<std::string> scope_node_id;
  int output_slot = 0;
  std::optional<TagTarget> target;  // default: scope_root
  TopologyPropagation topology = TopologyPropagation::Local;
  LineagePolicy lineage = LineagePolicy::ContinuationFragment;
  std::vector<LineageDerivation> explicit_derivations;
  std::optional<TagEvidence> evidence;  // default: user_assertion {authoring_source: simplecadapi.apply_tag}
};

// user_tag_binding: a canonical user assertion with explicit frozen policies.
TagBinding user_tag_binding(std::string_view tag, const UserTagOptions& options = {});

struct InternalTagOptions {
  TopologyPropagation topology = TopologyPropagation::Local;
  std::string rule_id = "simplecad.compat.internal_annotation";
  std::string rule_version = "1.0";
  Value evidence = Value::object();  // merged after {"source": "internal_annotation"}
};

// internal_tag_binding: a source-marked binding for transitional internal annotations.
TagBinding internal_tag_binding(std::string_view tag, const InternalTagOptions& options = {});

// operation_role_tag_binding: deterministic binding (uuid5) for a kernel-proven output role.
TagBinding operation_role_tag_binding(std::string_view tag, std::string_view operation, std::string_view role,
                                      std::string_view target_topo_id, std::string_view evidence_method);

// projected_tag_binding: one source binding projected through a proven feature-generation witness.
TagBinding projected_tag_binding(const TagBinding& source, std::string_view operation, std::string_view role,
                                 std::string_view source_topo_id, std::string_view target_topo_id,
                                 std::string_view evidence_method,
                                 TopologyPropagation topology = TopologyPropagation::Local);

// legacy_tag_binding: import one flat compatibility token without inventing assignment intent.
TagBinding legacy_tag_binding(std::string_view tag, std::optional<std::string_view> diagnostic = std::nullopt);

// uuid5(NAMESPACE_URL, name).hex: the deterministic ids Python derives binding ids from.
std::string uuid5_url_hex(std::string_view name);

// ---------------------------------------------------------------------------
// Lineage rules
// ---------------------------------------------------------------------------

// Whether a binding with this lineage policy may follow `derivation`.  An
// `explicit` policy needs the propagation record: pass the TagPropagation overload.
bool lineage_policy_allows(LineagePolicy policy, LineageDerivation derivation);
bool lineage_policy_allows(const TagPropagation& propagation, LineageDerivation derivation);
inline bool lineage_policy_allows(const Cow<TagPropagation>& propagation, LineageDerivation derivation) {
  return lineage_policy_allows(*propagation, derivation);
}

// ---------------------------------------------------------------------------
// Legacy token registry hints
// ---------------------------------------------------------------------------

struct TagPolicy {
  std::vector<std::string> propagate_prefixes{"role.", "anchor.", "group."};
  std::vector<std::string> propagate_exact{"top", "bottom", "left", "right", "front", "back", "side", "surface"};
  std::vector<std::string> block_prefixes{"feature.", "state.",  "face.",  "edge.",
                                          "wire.",    "vertex.", "solid.", "legacy."};
  std::vector<std::string> block_exact;

  // The old registry hint; assignment policy does not consult it.
  bool should_propagate(std::string_view tag) const;
};

const TagPolicy& default_tag_policy();

// Candidate tags for legacy anchor lookup, most specific first.
std::vector<std::string> resolve_anchor_tag_candidates(std::string_view tag);

// ---------------------------------------------------------------------------
// Wire format (from_dict): strict, like the Python classmethods.  TagValidationError on malformed input.
// ---------------------------------------------------------------------------
TagBindingScope tag_binding_scope_from_value(const Value& value);
TagProducer tag_producer_from_value(const Value& value);
TagTarget tag_target_from_value(const Value& value);
TagPropagation tag_propagation_from_value(const Value& value);
TagEvidence tag_evidence_from_value(const Value& value);
TagBinding tag_binding_from_value(const Value& value);
TagLineageWitness tag_lineage_witness_from_value(const Value& value);

// ---------------------------------------------------------------------------
// Equality (dataclass equality in Python)
// ---------------------------------------------------------------------------
bool operator==(const TagProducer& a, const TagProducer& b);
bool operator==(const TagBinding& a, const TagBinding& b);
bool operator==(const TagLineageWitness& a, const TagLineageWitness& b);

}  // namespace scad
