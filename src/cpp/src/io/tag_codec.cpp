#include "tag_codec.hpp"

#include <string>

#include "scad/core/error.hpp"

namespace scad::io::detail {

namespace {

const Value& member(const Value& object, std::string_view key, std::string_view where) {
  if (!object.is_object())
    throw ValueError("tag record: " + std::string(where) + " must be an object");
  const Value* found = object.find(key);
  if (found == nullptr)
    throw ValueError("tag record: " + std::string(where) + " has no '" + std::string(key) + "'");
  return *found;
}

const std::string& text(const Value& value, std::string_view what) {
  if (!value.is_string())
    throw ValueError("tag record: " + std::string(what) + " must be a string");
  return value.as_string();
}

std::optional<std::string> optional_text(const Value& object, std::string_view key, std::string_view where) {
  const Value* found = object.find(key);
  if (found == nullptr || found->is_null())
    return std::nullopt;
  return text(*found, std::string(where) + "." + std::string(key));
}

TagEvidence evidence_from(const Value& value) {
  TagEvidence evidence;
  evidence.kind = parse_tag_evidence_kind(text(member(value, "kind", "evidence"), "evidence.kind"));
  evidence.data = Value::object();
  for (const auto& [key, item] : value.as_object())
    if (key != "kind")
      evidence.data.set(key, item);
  return evidence;
}

}  // namespace

TagBinding binding_from_value(const Value& value) {
  TagBinding b;
  b.policy.mut().schema_version = text(member(value, "schema_version", "binding"), "schema_version");
  b.binding_id = text(member(value, "binding_id", "binding"), "binding_id");
  b.tag = text(member(value, "tag", "binding"), "tag");

  const Value& producer = member(value, "producer", "binding");
  b.policy.mut().producer.kind = parse_tag_producer_kind(text(member(producer, "kind", "producer"), "producer.kind"));
  b.policy.mut().producer.node_id = optional_text(producer, "node_id", "producer");
  b.policy.mut().producer.rule_id = optional_text(producer, "rule_id", "producer");
  b.policy.mut().producer.rule_version = optional_text(producer, "rule_version", "producer");

  const Value& scope = member(value, "scope", "binding");
  b.policy.mut().scope.node_id = optional_text(scope, "node_id", "scope");
  b.policy.mut().scope.output_slot = static_cast<int>(member(scope, "output_slot", "scope").as_int());

  const Value& target = member(value, "target", "binding");
  b.policy.mut().target.kind = parse_tag_target_kind(text(member(target, "kind", "target"), "target.kind"));
  b.policy.mut().target.query_hash = optional_text(target, "query_hash", "target");
  b.policy.mut().target.binding_hash = optional_text(target, "binding_hash", "target");
  if (const Value* selector = target.find("selector"))
    b.policy.mut().target.selector = *selector;
  if (const Value* refs = target.find("refs"))
    for (const Value& ref : refs->as_array())
      b.policy.mut().target.refs.push_back(ref);

  b.attachment = parse_tag_attachment(text(member(value, "attachment", "binding"), "attachment"));

  const Value& propagation = member(value, "propagation", "binding");
  b.policy.mut().propagation.topology =
      parse_topology_propagation(text(member(propagation, "topology", "propagation"), "propagation.topology"));
  b.policy.mut().propagation.lineage =
      parse_lineage_policy(text(member(propagation, "lineage", "propagation"), "propagation.lineage"));
  if (const Value* derivations = propagation.find("derivations"))
    for (const Value& d : derivations->as_array())
      b.policy.mut().propagation.explicit_derivations.push_back(
          parse_lineage_derivation(text(d, "propagation.derivations[]")));

  b.evidence = evidence_from(member(value, "evidence", "binding"));
  b.certainty = parse_tag_certainty(text(member(value, "certainty", "binding"), "certainty"));
  b.lifecycle = parse_tag_lifecycle(text(member(value, "lifecycle", "binding"), "lifecycle"));
  return b;
}

TagLineageWitness witness_from_value(const Value& value) {
  TagLineageWitness w;
  w.binding = binding_from_value(member(value, "binding", "lineage witness"));
  w.derivation = parse_lineage_derivation(text(member(value, "derivation", "lineage witness"), "derivation"));
  w.source_topo_id = text(member(value, "source_topo_id", "lineage witness"), "source_topo_id");
  w.target_topo_id = text(member(value, "target_topo_id", "lineage witness"), "target_topo_id");
  w.evidence = evidence_from(member(value, "evidence", "lineage witness"));
  w.coverage = text(member(value, "coverage", "lineage witness"), "coverage");
  return w;
}

}  // namespace scad::io::detail
