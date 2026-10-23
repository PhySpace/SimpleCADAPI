"""Unified durable product capture boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..artifacts.assembly_definition import AssemblyDefinition
from ..artifacts.assembly_io import materialize_definition
from ..artifacts.part_definition import PartDefinition
from simplecadapi._cpp import Assembly, Part
from .packages import (
    ProductPackage,
    build_product_package,
    encode_product_package,
)
from ..scene.product_scene import ProductScenePackage, read_scene_package


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """Runtime value plus one complete durable product snapshot."""

    value: Part | Assembly
    definition: PartDefinition | AssemblyDefinition
    package: ProductPackage
    scene: ProductScenePackage | None
    package_bytes: bytes


def capture(
    result: Any,
    path: str | Path,
    /,
    *,
    include_scene: bool = True,
) -> CaptureResult:
    """Capture a durable product and write its canonical `.scadpkg`.

    ``include_scene=False`` skips the optional Scene projection (tessellated
    geometry/entity assets). STEP, MJCF, and FreeCAD exports read meshes and
    feature graphs from the definition closure, so they do not need it.
    """

    definition = (
        result
        if isinstance(result, (PartDefinition, AssemblyDefinition))
        else getattr(result, "definition", None)
    )
    if not isinstance(definition, (PartDefinition, AssemblyDefinition)):
        raise TypeError(
            "result must be a PartDefinition, AssemblyDefinition, PartBuildResult, "
            "or AssemblyBuildResult"
        )
    runtime = getattr(result, "value", None)
    if runtime is None:
        runtime = materialize_definition(definition)
    if not isinstance(runtime, (Part, Assembly)):
        raise TypeError("captured runtime must be a Part or Assembly")
    runtime_kind = "single_solid" if isinstance(runtime, Part) else "assembly"
    runtime_definition_hash = runtime._get_runtime("definition.content_hash")
    if runtime_definition_hash is not None and runtime_definition_hash != definition.content_hash:
        raise ValueError("captured runtime does not match its durable definition")
    runtime_definition_kind = runtime._get_runtime("definition.kind")
    if runtime_definition_kind is not None and runtime_definition_kind != runtime_kind:
        raise ValueError("captured runtime definition kind is invalid")
    if runtime_kind != definition.definition_kind:
        raise ValueError("captured runtime kind does not match its durable definition")
    package = build_product_package(definition, include_scene=include_scene)
    package_bytes = encode_product_package(package)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(package_bytes)
    scene = (
        read_scene_package(package.scene_bytes)
        if package.scene_path is not None
        else None
    )
    return CaptureResult(
        value=runtime,
        definition=definition,
        package=package,
        scene=scene,
        package_bytes=package_bytes,
    )


__all__ = ["CaptureResult", "capture"]
