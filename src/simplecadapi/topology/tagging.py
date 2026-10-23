"""``simplecadapi.topology.tagging``: the C++ module's ``tagging`` namespace.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_semantic.cpp`` -> ``src/cpp/src/semantic``
"""

from __future__ import annotations

import simplecadapi._cpp as _cpp

_ns = _cpp.tagging

# bind_semantic.cpp
TagBinding = _ns.TagBinding
TagBindingScope = _ns.TagBindingScope
TagEvidence = _ns.TagEvidence
TagLineageWitness = _ns.TagLineageWitness
TagPolicy = _ns.TagPolicy
TagProducer = _ns.TagProducer
TagPropagation = _ns.TagPropagation
TagTarget = _ns.TagTarget
internal_tag_binding = _ns.internal_tag_binding
is_normalized_tag = _ns.is_normalized_tag
legacy_tag_binding = _ns.legacy_tag_binding
lineage_policy_allows = _ns.lineage_policy_allows
normalize_tag = _ns.normalize_tag
normalize_tag_scope = _ns.normalize_tag_scope
operation_role_tag_binding = _ns.operation_role_tag_binding
projected_tag_binding = _ns.projected_tag_binding
resolve_anchor_tag_candidates = _ns.resolve_anchor_tag_candidates
user_tag_binding = _ns.user_tag_binding
# (defined in Python or by the module itself)
Attachment = _ns.Attachment
BindingScope = _ns.BindingScope
Certainty = _ns.Certainty
DEFAULT_TAG_POLICY = _ns.DEFAULT_TAG_POLICY
Evidence = _ns.Evidence
EvidenceKind = _ns.EvidenceKind
Lifecycle = _ns.Lifecycle
Lineage = _ns.Lineage
LineageDerivation = _ns.LineageDerivation
LineagePolicy = _ns.LineagePolicy
Producer = _ns.Producer
ProducerKind = _ns.ProducerKind
Propagation = _ns.Propagation
SemanticCapabilityError = _ns.SemanticCapabilityError
TAG_BINDING_SCHEMA_VERSION = _ns.TAG_BINDING_SCHEMA_VERSION
TagAttachment = _ns.TagAttachment
TagCertainty = _ns.TagCertainty
TagEvidenceKind = _ns.TagEvidenceKind
TagLifecycle = _ns.TagLifecycle
TagProducerKind = _ns.TagProducerKind
TagScope = _ns.TagScope
TagTargetKind = _ns.TagTargetKind
TagValidationError = _ns.TagValidationError
Target = _ns.Target
TargetKind = _ns.TargetKind
TopologyPropagation = _ns.TopologyPropagation
UnsupportedQueryCapabilityError = _ns.UnsupportedQueryCapabilityError
VALID_TAG_SCOPES = _ns.VALID_TAG_SCOPES

__all__ = [
    "Attachment",
    "BindingScope",
    "Certainty",
    "DEFAULT_TAG_POLICY",
    "Evidence",
    "EvidenceKind",
    "Lifecycle",
    "Lineage",
    "LineageDerivation",
    "LineagePolicy",
    "Producer",
    "ProducerKind",
    "Propagation",
    "SemanticCapabilityError",
    "TAG_BINDING_SCHEMA_VERSION",
    "TagAttachment",
    "TagBinding",
    "TagBindingScope",
    "TagCertainty",
    "TagEvidence",
    "TagEvidenceKind",
    "TagLifecycle",
    "TagLineageWitness",
    "TagPolicy",
    "TagProducer",
    "TagProducerKind",
    "TagPropagation",
    "TagScope",
    "TagTarget",
    "TagTargetKind",
    "TagValidationError",
    "Target",
    "TargetKind",
    "TopologyPropagation",
    "UnsupportedQueryCapabilityError",
    "VALID_TAG_SCOPES",
    "internal_tag_binding",
    "is_normalized_tag",
    "legacy_tag_binding",
    "lineage_policy_allows",
    "normalize_tag",
    "normalize_tag_scope",
    "operation_role_tag_binding",
    "projected_tag_binding",
    "resolve_anchor_tag_candidates",
    "user_tag_binding",
]
