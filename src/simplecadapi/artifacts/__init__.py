"""Persistent PartDefinition and AssemblyDefinition artifact contracts."""

from .assembly_definition import AssemblyDefinition
from .assembly_io import (
    decode_assembly_definition,
    encode_assembly_definition,
    export_assembly_definition,
    load_assembly_definition,
    materialize_definition,
    validate_assembly_definition_graph,
)
from .canonical import (
    ARTIFACT_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_LIMITS,
    ArtifactLimits,
    ArtifactValidationError,
)
from .feature_graph import (
    FeatureGraphArtifact,
    SourceFileSnapshot,
    encode_feature_graph_artifact,
    load_feature_graph_artifact,
)
from .geometry_interface import (
    geometry_interface_descriptor,
    geometry_interface_fingerprint,
)
from .part_definition import PartDefinition
from .part_io import (
    encode_part_definition,
    export_part_definition,
    load_part_definition,
)
from .references import (
    BlobRef,
    ConnectorInterface,
    FileInputSnapshot,
    InterfaceHashes,
    MaterialRef,
    PartInstance,
    PartRef,
)

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "ArtifactLimits",
    "ArtifactValidationError",
    "AssemblyDefinition",
    "BlobRef",
    "FeatureGraphArtifact",
    "SourceFileSnapshot",
    "encode_feature_graph_artifact",
    "load_feature_graph_artifact",
    "decode_assembly_definition",
    "encode_assembly_definition",
    "export_assembly_definition",
    "load_assembly_definition",
    "materialize_definition",
    "validate_assembly_definition_graph",
    "ConnectorInterface",
    "encode_part_definition",
    "export_part_definition",
    "load_part_definition",
    "geometry_interface_descriptor",
    "geometry_interface_fingerprint",
    "DEFAULT_ARTIFACT_LIMITS",
    "FileInputSnapshot",
    "InterfaceHashes",
    "MaterialRef",
    "PartInstance",
    "PartDefinition",
    "PartRef",
]
