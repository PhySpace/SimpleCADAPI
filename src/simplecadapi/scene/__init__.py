"""Validated Scene Schema 1.0 contract primitives.

This package contains the validated Scene Schema boundary, deterministic
compiler/exporter, and the browser-facing evaluated mesh encoders.
"""

from .archive import (
    ArchiveInfo,
    canonical_zip_bytes,
    preflight_archive_member_sizes,
    preflight_unpacked_scene,
    preflight_zip_bytes,
)
from .canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    compute_scene_revision,
    parse_canonical_json,
    parse_strict_json,
    with_scene_revision,
)
from .documents import (
    ConnectorBindingDocument,
    EntityDocument,
    NormalizedProductDocument,
    PresentationDocument,
    SceneDocument,
)
from .glb import (
    GlbInfo,
    preflight_glb,
    preflight_glb_counts,
    profile_cross,
    profile_f32,
    profile_f32_bits,
    profile_normalize,
)
from .resources import (
    BASE_LIMITS,
    SceneResourceLimits,
    canonical_archive_size,
    preflight_aggregate_compression_ratio,
    preflight_input_archive_size,
    preflight_member_compression_ratio,
    preflight_resource_count,
)
from .validation import (
    SCHEMA_FILES,
    SceneContractError,
    SceneValidationIssue,
    SceneValidationReport,
    assert_connector_binding,
    assert_entity_asset,
    assert_normalized_product,
    assert_presentation,
    assert_scene_manifest,
    assert_scene_package,
    load_contract_artifact,
    validate_connector_binding,
    validate_entity_asset,
    validate_normalized_product,
    validate_presentation,
    validate_scene_manifest,
    validate_scene_package,
    json_resource_issues,
    resource_count_issues,
)


def __getattr__(name: str):
    if name in {
        "ProductSceneError",
        "ProductScenePackage",
        "compile_product_scene",
        "encode_product_scene",
        "read_scene_package",
        "validate_product_scene_package",
    }:
        from . import product_scene

        return getattr(product_scene, name)
    return _lazy_name(name)


_LAZY = {'CompiledScenePackage': 'compiler', 'SceneCompileOptions': 'compiler', 'SceneRoot': 'compiler', 'SceneSource': 'compiler', 'compile_scene': 'compiler', 'export_scene': 'compiler', 'write_line_glb': 'glb_writer', 'write_triangle_glb': 'glb_writer', 'CanonicalEdgeBlock': 'render_mesh', 'CanonicalTriangleBlock': 'render_mesh', 'RenderEdgeMesh': 'render_mesh', 'RenderGroup': 'render_mesh', 'RenderMesh': 'render_mesh', 'build_edge_mesh': 'render_mesh', 'build_render_mesh': 'render_mesh', 'cad_direction_to_gltf': 'render_mesh', 'cad_to_gltf': 'render_mesh', 'solid_asset_bounds': 'render_mesh'}
"""Names served from the submodules that need OCP (tessellation, face geometry), imported on first use."""


def _lazy_name(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


__all__ = [
    "ArchiveInfo",
    "BASE_LIMITS",
    "ConnectorBindingDocument",
    "CanonicalEdgeBlock",
    "CanonicalTriangleBlock",
    "CompiledScenePackage",
    "EntityDocument",
    "GlbInfo",
    "NormalizedProductDocument",
    "PresentationDocument",
    "ProductSceneError",
    "ProductScenePackage",
    "SCHEMA_FILES",
    "SceneContractError",
    "SceneDocument",
    "SceneCompileOptions",
    "SceneRoot",
    "SceneSource",
    "SceneResourceLimits",
    "SceneValidationIssue",
    "SceneValidationReport",
    "assert_connector_binding",
    "assert_entity_asset",
    "assert_normalized_product",
    "assert_presentation",
    "assert_scene_manifest",
    "assert_scene_package",
    "canonical_json_bytes",
    "canonical_json_hash",
    "canonical_archive_size",
    "canonical_zip_bytes",
    "compute_scene_revision",
    "load_contract_artifact",
    "parse_canonical_json",
    "parse_strict_json",
    "preflight_glb",
    "preflight_glb_counts",
    "preflight_archive_member_sizes",
    "preflight_input_archive_size",
    "preflight_aggregate_compression_ratio",
    "preflight_member_compression_ratio",
    "preflight_resource_count",
    "preflight_unpacked_scene",
    "preflight_zip_bytes",
    "profile_cross",
    "profile_f32",
    "profile_f32_bits",
    "profile_normalize",
    "validate_connector_binding",
    "validate_entity_asset",
    "validate_normalized_product",
    "validate_presentation",
    "validate_scene_manifest",
    "validate_scene_package",
    "RenderEdgeMesh",
    "RenderGroup",
    "RenderMesh",
    "build_edge_mesh",
    "build_render_mesh",
    "cad_direction_to_gltf",
    "cad_to_gltf",
    "compile_product_scene",
    "encode_product_scene",
    "read_scene_package",
    "validate_product_scene_package",
    "compile_scene",
    "export_scene",
    "json_resource_issues",
    "resource_count_issues",
    "with_scene_revision",
    "solid_asset_bounds",
    "write_line_glb",
    "write_triangle_glb",
]
