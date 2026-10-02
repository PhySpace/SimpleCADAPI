"""Generate a named three-dimensional Gmsh FEM mesh from AP242 STEP."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
import json
from pathlib import Path
from typing import Any

import simplecadapi as scad
from simplecadapi.scene import parse_canonical_json, read_scene_package


OUT_DIR = Path(__file__).resolve().parent / "out"
PACKAGE_PATH = OUT_DIR / "ap242_gmsh_bracket.scadpkg"
STEP_PATH = OUT_DIR / "ap242_gmsh_bracket.step"
MESH_PATH = OUT_DIR / "ap242_gmsh_bracket.msh"
MAPPING_PATH = OUT_DIR / "ap242_gmsh_bracket.gmsh.json"


@dataclass(frozen=True, slots=True)
class GmshMeshReport:
    step_path: Path
    mesh_path: Path
    mapping_path: Path | None
    volume_count: int
    node_count: int
    element_count: int
    interface_count: int


def _interface_faces(package_path: Path) -> list[dict[str, Any]]:
    package = scad.read_product_package(package_path)
    scene = read_scene_package(package.scene_bytes)
    result: list[dict[str, Any]] = []
    for record in scene.manifest["entity_assets"]:
        document = parse_canonical_json(scene.blobs[record["uri"]])
        for entity in document["entities"]:
            if entity["kind"] != "face":
                continue
            tags = [str(tag) for tag in entity["tags"] if str(tag).startswith("interface.")]
            for tag in tags:
                result.append(
                    {
                        "name": tag,
                        "definition_id": document["definition_id"],
                        "entity_id": entity["entity_id"],
                        "topo_id": entity["topo_id"],
                        "area": float(entity["properties"]["area"]),
                        "centroid": [float(value) for value in entity["properties"]["centroid"]],
                        "bounds": {
                            key: [float(value) for value in entity["properties"]["bounds"][key]]
                            for key in ("min", "max")
                        },
                    }
                )
    names = [item["name"] for item in result]
    if len(names) != len(set(names)):
        raise ValueError("interface face tags must be unique within the meshed product")
    return sorted(result, key=lambda item: item["name"])


def _surface_signature(gmsh: Any, tag: int) -> dict[str, Any]:
    bounds = gmsh.model.getBoundingBox(2, tag)
    return {
        "area": float(gmsh.model.occ.getMass(2, tag)),
        "centroid": [float(value) for value in gmsh.model.occ.getCenterOfMass(2, tag)],
        "bounds": {
            "min": [float(value) for value in bounds[:3]],
            "max": [float(value) for value in bounds[3:]],
        },
    }


def _signature_error(target: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, float, float]:
    area_error = abs(candidate["area"] - target["area"]) / max(1.0, abs(target["area"]))
    center_error = max(
        abs(candidate["centroid"][index] - target["centroid"][index])
        for index in range(3)
    )
    bounds_error = max(
        abs(candidate["bounds"][side][index] - target["bounds"][side][index])
        for side in ("min", "max")
        for index in range(3)
    )
    return area_error, center_error, bounds_error


def _match_interface_surfaces(gmsh: Any, interfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    available = {
        int(tag): _surface_signature(gmsh, int(tag))
        for dimension, tag in gmsh.model.getEntities(2)
        if dimension == 2
    }
    matched: list[dict[str, Any]] = []
    used: set[int] = set()
    for interface in interfaces:
        candidates = []
        for surface_tag, signature in available.items():
            if surface_tag in used:
                continue
            error = _signature_error(interface, signature)
            candidates.append((error, surface_tag, signature))
        if not candidates:
            raise RuntimeError(f"no Gmsh surface remains for {interface['name']}")
        error, surface_tag, signature = min(
            candidates,
            key=lambda item: (item[0][1], item[0][2], item[0][0]),
        )
        area_error, center_error, bounds_error = error
        if area_error > 1.0e-6 or center_error > 1.0e-5 or bounds_error > 0.05:
            raise RuntimeError(
                f"could not match {interface['name']} to imported STEP surface: "
                f"area_error={area_error:.3g}, center_error={center_error:.3g} mm, "
                f"bounds_error={bounds_error:.3g} mm"
            )
        used.add(surface_tag)
        matched.append(
            {
                **interface,
                "gmsh_surface_tag": surface_tag,
                "gmsh_signature": signature,
                "match_error": {
                    "relative_area": area_error,
                    "centroid_mm": center_error,
                    "bounds_mm": bounds_error,
                },
            }
        )
    return matched


def mesh_step_with_gmsh(
    step_path: str | Path,
    mesh_path: str | Path,
    *,
    package_path: str | Path | None = None,
    mapping_path: str | Path | None = None,
    mesh_size: float = 2.0,
    gmsh_module: Any | None = None,
) -> GmshMeshReport:
    """Import STEP, create semantic physical groups, and write a 3D MSH mesh."""

    if mesh_size <= 0.0:
        raise ValueError("mesh_size must be positive")
    source = Path(step_path).expanduser().resolve()
    destination = Path(mesh_path).expanduser().resolve()
    package = Path(package_path).expanduser().resolve() if package_path is not None else None
    mapping = Path(mapping_path).expanduser().resolve() if mapping_path is not None else None
    if not source.is_file():
        raise FileNotFoundError(f"Run export_step.py first: {source}")
    if package is not None and not package.is_file():
        raise FileNotFoundError(f"Run export_step.py first: {package}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mapping is not None:
        mapping.parent.mkdir(parents=True, exist_ok=True)
    interfaces = _interface_faces(package) if package is not None else []

    gmsh = gmsh_module
    if gmsh is None:
        try:
            gmsh = importlib.import_module("gmsh")
        except ImportError as exc:
            raise RuntimeError(
                "Gmsh is optional; install it with `pip install simplecadapi[gmsh]`"
            ) from exc

    initialized = False
    matched: list[dict[str, Any]] = []
    try:
        gmsh.initialize()
        initialized = True
        gmsh.model.add(source.stem)
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        imported = gmsh.model.occ.importShapes(str(source))
        gmsh.model.occ.synchronize()
        volumes = gmsh.model.getEntities(3)
        if not volumes:
            raise RuntimeError(
                f"Gmsh imported no 3D volumes from {source}; imported entities: {imported}"
            )
        volume_group = gmsh.model.addPhysicalGroup(3, [tag for _dimension, tag in volumes])
        gmsh.model.setPhysicalName(3, volume_group, "body.ap242_gmsh_bracket")
        matched = _match_interface_surfaces(gmsh, interfaces)
        for item in matched:
            group = gmsh.model.addPhysicalGroup(2, [item["gmsh_surface_tag"]])
            gmsh.model.setPhysicalName(2, group, item["name"])
            item["physical_group_tag"] = int(group)
        gmsh.option.setNumber("Mesh.MeshSizeMin", float(mesh_size))
        gmsh.option.setNumber("Mesh.MeshSizeMax", float(mesh_size))
        gmsh.model.mesh.generate(3)
        node_tags, _coordinates, _parameters = gmsh.model.mesh.getNodes()
        _types, element_tags, _node_tags = gmsh.model.mesh.getElements(3)
        element_count = sum(len(tags) for tags in element_tags)
        if not len(node_tags) or not element_count:
            raise RuntimeError("Gmsh generated an empty 3D mesh")
        gmsh.write(str(destination))
    finally:
        if initialized:
            gmsh.finalize()

    if not destination.is_file() or destination.stat().st_size <= 0:
        raise RuntimeError(f"Gmsh did not create a non-empty mesh file at {destination}")
    if mapping is not None:
        mapping.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "source_step": str(source),
                    "source_package": str(package) if package is not None else None,
                    "volume_physical_name": "body.ap242_gmsh_bracket",
                    "interfaces": matched,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return GmshMeshReport(
        step_path=source,
        mesh_path=destination,
        mapping_path=mapping,
        volume_count=len(volumes),
        node_count=len(node_tags),
        element_count=element_count,
        interface_count=len(matched),
    )


def main(*, mesh_size: float = 2.0) -> None:
    report = mesh_step_with_gmsh(
        STEP_PATH,
        MESH_PATH,
        package_path=PACKAGE_PATH,
        mapping_path=MAPPING_PATH,
        mesh_size=mesh_size,
    )
    print("gmsh_mesh", report.mesh_path)
    print("gmsh_mapping", report.mapping_path)
    print("gmsh_volumes", report.volume_count)
    print("gmsh_interfaces", report.interface_count)
    print("gmsh_nodes", report.node_count)
    print("gmsh_3d_elements", report.element_count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh-size", type=float, default=2.0)
    args = parser.parse_args()
    main(mesh_size=args.mesh_size)
