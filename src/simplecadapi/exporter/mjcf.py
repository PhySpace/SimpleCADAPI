"""MuJoCo MJCF export for validated SimpleCAD product packages."""

from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping
import xml.etree.ElementTree as ET

import numpy as np

from ..artifacts.assembly_io import materialize_definition
from ..artifacts.canonical import parse_canonical_json
from ..artifacts.part_definition import PartDefinition
from simplecadapi._cpp import Assembly, Part
from ..product.placement import Placement, relative_placement
from ..translator.package_units import (
    ProductPackageInput,
    read_product_package_translation_units,
)
from ._surface_mesh import tessellate_solid

_DEFAULT_MJCF_ANGULAR_DEFLECTION_DEGREES = math.degrees(0.35)


@dataclass(frozen=True, slots=True)
class ProductMJCFExportReport:
    """Observed facts and compiler decisions from one MJCF export."""

    output_path: Path
    mapping_path: Path
    mesh_directory: Path
    root_definition_id: str
    mesh_count: int
    body_count: int
    joint_count: int
    equality_count: int
    closure_count: int
    grounded_group_count: int
    site_count: int
    default_density_count: int
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "mapping_path": str(self.mapping_path),
            "mesh_directory": str(self.mesh_directory),
            "root_definition_id": self.root_definition_id,
            "mesh_count": self.mesh_count,
            "body_count": self.body_count,
            "joint_count": self.joint_count,
            "equality_count": self.equality_count,
            "closure_count": self.closure_count,
            "site_count": self.site_count,
            "default_density_count": self.default_density_count,
            "limitations": list(self.limitations),
        }


class _UnionFind:
    def __init__(self, values: list[str]) -> None:
        self.parent = {value: value for value in values}
        self.rank = {value: 0 for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, first: str, second: str) -> None:
        left = self.find(first)
        right = self.find(second)
        if left == right:
            return
        if self.rank[left] < self.rank[right]:
            left, right = right, left
        self.parent[right] = left
        if self.rank[left] == self.rank[right]:
            self.rank[left] += 1


def _safe_name(value: str, *, prefix: str = "item") -> str:
    source = str(value)
    rendered = re.sub(r"[^A-Za-z0-9_]", "_", source).strip("_")
    if not rendered:
        rendered = prefix
    if not rendered[0].isalpha():
        rendered = f"{prefix}_{rendered}"
    if rendered != source or len(rendered) > 96:
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
        rendered = f"{rendered[:80]}_{digest}"
    return rendered


class _NameRegistry:
    def __init__(self) -> None:
        self._owners: dict[str, dict[str, str]] = defaultdict(dict)

    def claim(
        self,
        namespace: str,
        value: str,
        *,
        identity: str,
        prefix: str,
    ) -> str:
        candidate = _safe_name(value, prefix=prefix)
        owners = self._owners[namespace]
        owner = owners.get(candidate)
        if owner is None or owner == identity:
            owners[candidate] = identity
            return candidate
        digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
        candidate = f"{candidate[:80]}_{digest}"
        owner = owners.get(candidate)
        if owner is not None and owner != identity:
            raise ValueError(
                f"MJCF {namespace} names collide for {owner!r} and {identity!r}"
            )
        owners[candidate] = identity
        return candidate


def _fmt(value: float) -> str:
    return f"{float(value):.12g}"


def _fmt_vec(values: tuple[float, float, float] | list[float]) -> str:
    return " ".join(_fmt(float(value)) for value in values)


def _placement(payload: Mapping[str, Any]) -> Placement:
    return Placement(
        origin=tuple(float(value) for value in payload["origin"]),
        x_axis=tuple(float(value) for value in payload["x_axis"]),
        y_axis=tuple(float(value) for value in payload["y_axis"]),
        z_axis=tuple(float(value) for value in payload["z_axis"]),
    )


def _inverse_vector(
    frame: Placement,
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        sum(vector[index] * frame.x_axis[index] for index in range(3)),
        sum(vector[index] * frame.y_axis[index] for index in range(3)),
        sum(vector[index] * frame.z_axis[index] for index in range(3)),
    )


def _add_scaled_terms(
    target: dict[str, float],
    source: Mapping[str, float],
    scale: float,
) -> None:
    for name, coefficient in source.items():
        target[name] = target.get(name, 0.0) + scale * coefficient


def _subtracted_terms(
    first: Mapping[str, float],
    second: Mapping[str, float],
) -> dict[str, float]:
    result = dict(first)
    _add_scaled_terms(result, second, -1.0)
    return {name: value for name, value in result.items() if abs(value) > 1.0e-12}


def _matrix_to_quat(frame: Placement) -> tuple[float, float, float, float]:
    """Convert the frame's orthonormal columns to MuJoCo wxyz."""

    m00, m01, m02 = frame.x_axis[0], frame.y_axis[0], frame.z_axis[0]
    m10, m11, m12 = frame.x_axis[1], frame.y_axis[1], frame.z_axis[1]
    m20, m21, m22 = frame.x_axis[2], frame.y_axis[2], frame.z_axis[2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        scale = 2.0 * (trace + 1.0) ** 0.5
        return (
            0.25 * scale,
            (m21 - m12) / scale,
            (m02 - m20) / scale,
            (m10 - m01) / scale,
        )
    if m00 > m11 and m00 > m22:
        scale = 2.0 * (1.0 + m00 - m11 - m22) ** 0.5
        return (
            (m21 - m12) / scale,
            0.25 * scale,
            (m01 + m10) / scale,
            (m02 + m20) / scale,
        )
    if m11 > m22:
        scale = 2.0 * (1.0 + m11 - m00 - m22) ** 0.5
        return (
            (m02 - m20) / scale,
            (m01 + m10) / scale,
            0.25 * scale,
            (m12 + m21) / scale,
        )
    scale = 2.0 * (1.0 + m22 - m00 - m11) ** 0.5
    return (
        (m10 - m01) / scale,
        (m02 + m20) / scale,
        (m12 + m21) / scale,
        0.25 * scale,
    )


def _placement_attributes(value: Placement, *, scale_length: bool) -> dict[str, str]:
    origin = (
        tuple(component * 0.001 for component in value.origin)
        if scale_length
        else value.origin
    )
    return {
        "pos": _fmt_vec(origin),
        "quat": _fmt_vec(_matrix_to_quat(value)),
    }


def _write_obj(
    path: Path,
    solid: Any,
    *,
    linear_deflection: float,
    angular_deflection_degrees: float,
) -> tuple[int, int]:
    vertices, triangles = tessellate_solid(
        solid,
        linear_deflection=linear_deflection,
        angular_deflection_degrees=angular_deflection_degrees,
        relative=False,
    )
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("# SimpleCAD BREP tessellation for MuJoCo\n")
        for x, y, z in vertices:
            stream.write(f"v {_fmt(float(x))} {_fmt(float(y))} {_fmt(float(z))}\n")
        for a, b, c in triangles:
            stream.write(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}\n")
    return int(len(vertices)), int(len(triangles))


def _density_kg_m3(
    material: Any,
    *,
    default_density_kg_m3: float | None,
) -> tuple[float, bool]:
    density = getattr(material, "density", None) if material is not None else None
    unit = (
        str(getattr(material, "density_unit", None) or "")
        if material is not None
        else ""
    )
    if density is None:
        if default_density_kg_m3 is None:
            raise ValueError(
                "MJCF export requires material density for every Part; pass "
                "default_density_kg_m3 explicitly to opt into a fallback"
            )
        return float(default_density_kg_m3), True
    if unit == "kg/mm^3":
        return float(density) * 1.0e9, False
    if unit in {"kg/m^3", "kg/m3"}:
        return float(density), False
    raise ValueError(f"unsupported material density unit for MJCF: {unit!r}")


def _world_placements(scene: Mapping[str, Any]) -> dict[str, Placement]:
    nodes = {str(item["node_id"]): item for item in scene["nodes"]}
    result: dict[str, Placement] = {}
    pending = set(nodes)
    while pending:
        progress = False
        for node_id in sorted(pending):
            node = nodes[node_id]
            parent_id = node["parent_node_id"]
            if parent_id is not None and parent_id not in result:
                continue
            local = _placement(node["transform"])
            result[node_id] = (
                local if parent_id is None else result[parent_id].compose(local)
            )
            pending.remove(node_id)
            progress = True
            break
        if not progress:
            raise ValueError("Scene node hierarchy contains an unresolved parent cycle")
    return result


def _runtime_ground_edges(value: Assembly, root_node_id: str) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []

    def visit(item: Part | Assembly, node_id: str) -> None:
        if not isinstance(item, Assembly):
            return
        for component in item.components:
            child_node_id = f"{node_id}/{component.component_id}"
            if component.component_id in item.grounded_component_ids:
                edges.append((node_id, child_node_id))
            visit(component.item, child_node_id)

    visit(value, root_node_id)
    return edges


def _entity_documents(
    scene_package: Any,
) -> dict[str, dict[str, Any]]:
    if scene_package is None:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for record in scene_package.manifest["entity_assets"]:
        document = parse_canonical_json(scene_package.blobs[record["uri"]])
        result[str(document["definition_id"])] = document
    return result


def _part_materials(units: tuple[Any, ...]) -> dict[str, tuple[Part, float, bool]]:
    result: dict[str, tuple[Part, float, bool]] = {}
    for unit in units:
        if not isinstance(unit.definition, PartDefinition):
            continue
        runtime = materialize_definition(unit.definition)
        if not isinstance(runtime, Part):
            raise TypeError(
                f"definition {unit.definition_id!r} did not materialize as Part"
            )
        result[unit.definition_id] = (runtime, 0.0, False)
    return result


def export_product_package_to_mjcf(
    data: ProductPackageInput,
    output_path: str | Path,
    *,
    mesh_directory: str | Path | None = None,
    mapping_path: str | Path | None = None,
    linear_deflection: float = 0.15,
    angular_deflection_degrees: float = _DEFAULT_MJCF_ANGULAR_DEFLECTION_DEGREES,
    default_density_kg_m3: float | None = None,
) -> ProductMJCFExportReport:
    """Compile a validated `.scadpkg` assembly into an MJCF model.
    Fixed constraints create rigid groups. Public connector declarations resolve
    endpoint ownership to their leaf connectors without changing the constraint
    kind. Revolute/prismatic edges form a deterministic spanning tree. Gear,
    belt, and rack-pinion relations become independent fixed-tendon
    equalities. Root assembly connectors and geometry names in the
    ``interface.*`` namespace become MJCF sites.
    """

    if not math.isfinite(float(linear_deflection)) or float(linear_deflection) <= 0.0:
        raise ValueError("linear_deflection must be a positive finite value")
    if not math.isfinite(float(angular_deflection_degrees)) or not (
        0.0 < float(angular_deflection_degrees) <= 180.0
    ):
        raise ValueError("angular_deflection_degrees must be in (0, 180]")
    destination = Path(output_path).expanduser().resolve()
    if destination.suffix.lower() != ".xml":
        raise ValueError("output_path must end in .xml")
    destination.parent.mkdir(parents=True, exist_ok=True)
    mesh_root = (
        Path(mesh_directory).expanduser().resolve()
        if mesh_directory is not None
        else destination.parent / f"{destination.stem}_meshes"
    )
    mesh_root.mkdir(parents=True, exist_ok=True)
    decision_path = (
        Path(mapping_path).expanduser().resolve()
        if mapping_path is not None
        else destination.with_suffix(".mapping.json")
    )
    decision_path.parent.mkdir(parents=True, exist_ok=True)

    package, units = read_product_package_translation_units(data)
    if (
        not hasattr(package.root_definition, "definition_kind")
        or package.root_definition.definition_kind != "assembly"
    ):
        raise ValueError("MJCF export requires an assembly-rooted .scadpkg")
    root_runtime = materialize_definition(package.root_definition)
    if not isinstance(root_runtime, Assembly):
        raise TypeError("assembly package root did not materialize as Assembly")
    occurrence = package.occurrence_graph
    scene_package = package.scene if package.scene_path is not None else None
    scene_nodes = (
        {str(item["node_id"]): item for item in scene_package.manifest["nodes"]}
        if scene_package is not None
        else {}
    )
    nodes = {
        str(item["node_id"]): {
            **dict(item),
            "entity_asset_id": scene_nodes.get(str(item["node_id"]), {}).get(
                "entity_asset_id"
            ),
        }
        for item in occurrence.nodes
    }
    world = _world_placements({"nodes": list(nodes.values())})
    root_node_id = occurrence.root_node_id
    connector_records = list(occurrence.connectors)
    connector_by_snapshot = {
        str(item["connector_snapshot_id"]): item for item in connector_records
    }
    connectors_by_node_and_id = {
        (str(item["node_id"]), str(item["connector_id"])): item
        for item in connector_records
    }
    def leaf_connector(record: Mapping[str, Any]) -> Mapping[str, Any]:
        current = record
        seen: set[str] = set()
        while current.get("source_connector_snapshot_id") is not None:
            snapshot_id = str(current["connector_snapshot_id"])
            if snapshot_id in seen:
                raise ValueError(f"public connector cycle at {snapshot_id!r}")
            seen.add(snapshot_id)
            source_snapshot_id = str(current["source_connector_snapshot_id"])
            try:
                current = connector_by_snapshot[source_snapshot_id]
            except KeyError as exc:
                raise ValueError(
                    f"public connector {snapshot_id!r} does not resolve to source snapshot {source_snapshot_id!r}"
                ) from exc
        return current

    uf = _UnionFind(sorted(nodes))
    rigid_edges: list[dict[str, str]] = []
    movable_edges: list[dict[str, Any]] = []
    equality_edges: list[dict[str, Any]] = []
    for first, second in _runtime_ground_edges(root_runtime, root_node_id):
        uf.union(first, second)
        rigid_edges.append({"kind": "ground", "a": first, "b": second})
    for joint in occurrence.joints:
        first_original = connector_by_snapshot[
            str(joint["connector_a"]["connector_snapshot_id"])
        ]
        second_original = connector_by_snapshot[
            str(joint["connector_b"]["connector_snapshot_id"])
        ]
        first_connector = leaf_connector(first_original)
        second_connector = leaf_connector(second_original)
        first = str(first_connector["node_id"])
        second = str(second_connector["node_id"])
        kind = str(joint["joint_type"])
        if kind == "fixed":
            uf.union(first, second)
            rigid_edges.append(
                {
                    "kind": kind,
                    "a": first,
                    "b": second,
                    "joint_id": str(joint["joint_id"]),
                }
            )
        elif kind in {"revolute", "prismatic"}:
            movable_edges.append(
                {
                    "joint": joint,
                    "a": first,
                    "b": second,
                    "connector_a": first_connector,
                    "connector_b": second_connector,
                }
            )
        elif kind in {"gear", "belt", "rack_pinion"}:
            equality_edges.append(
                {
                    "joint": joint,
                    "a": first,
                    "b": second,
                    "connector_a": first_connector,
                    "connector_b": second_connector,
                }
            )
        else:
            raise ValueError(f"MJCF exporter does not support joint type {kind!r}")

    groups: dict[str, list[str]] = defaultdict(list)
    for node_id in sorted(nodes):
        groups[uf.find(node_id)].append(node_id)
    root_group = uf.find(root_node_id)
    group_for_node = {node_id: uf.find(node_id) for node_id in nodes}
    group_representative: dict[str, str] = {}
    for group_id, members in groups.items():
        geometric = [
            node_id
            for node_id in members
            if nodes[node_id]["node_kind"] == "part"
            and nodes[node_id]["entity_asset_id"] is not None
        ]
        group_representative[group_id] = sorted(geometric or members)[0]

    movable_edges.sort(
        key=lambda item: (
            str(item["joint"]["assembly_definition_id"])
            != str(package.root_definition.definition_id),
            str(item["joint"]["joint_id"]),
        )
    )
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in movable_edges:
        first_group = group_for_node[edge["a"]]
        second_group = group_for_node[edge["b"]]
        if first_group == second_group:
            raise ValueError(
                f"movable joint {edge['joint']['joint_id']!r} collapsed inside a rigid grounding group"
            )
        edge["a_group"] = first_group
        edge["b_group"] = second_group
        adjacency[first_group].append(edge)
        adjacency[second_group].append(edge)

    parent_group: dict[str, str | None] = {root_group: None}
    parent_edge: dict[str, dict[str, Any]] = {}
    queue: deque[str] = deque([root_group])
    while queue:
        current = queue.popleft()
        for edge in sorted(
            adjacency[current],
            key=lambda item: (
                str(item["joint"]["assembly_definition_id"])
                != str(package.root_definition.definition_id),
                str(item["joint"]["joint_id"]),
            ),
        ):
            target = edge["b_group"] if edge["a_group"] == current else edge["a_group"]
            if target in parent_group:
                continue
            parent_group[target] = current
            parent_edge[target] = edge
            queue.append(target)
    unreachable = set(groups) - set(parent_group)
    pruned_group_ids = {
        group_id
        for group_id in unreachable
        if all(
            nodes[node_id]["node_kind"] == "assembly" for node_id in groups[group_id]
        )
        and group_id not in adjacency
    }
    disconnected = sorted(unreachable - pruned_group_ids)
    if disconnected:
        raise ValueError(
            "MJCF kinematic graph is disconnected from grounding; unreachable groups: "
            + ", ".join(disconnected)
        )
    pruned_structure_nodes = sorted(
        node_id for group_id in pruned_group_ids for node_id in groups[group_id]
    )
    groups = {
        group_id: members
        for group_id, members in groups.items()
        if group_id not in pruned_group_ids
    }

    names = _NameRegistry()
    body_name_by_group: dict[str, str] = {}
    for group_id, edge in parent_edge.items():
        joint = edge["joint"]
        group_component_id = None
        for side in ("a", "b"):
            endpoint = joint[f"connector_{side}"]
            endpoint_snapshot = connector_by_snapshot[
                str(endpoint["connector_snapshot_id"])
            ]
            if (
                group_for_node[str(leaf_connector(endpoint_snapshot)["node_id"])]
                == group_id
            ):
                group_component_id = str(endpoint["component_id"])
                break
        if group_component_id is None:
            raise ValueError(
                f"tree joint {joint['joint_id']!r} does not identify child group"
            )
        body_name_by_group[group_id] = names.claim(
            "body",
            f"body_{group_component_id}",
            identity=group_id,
            prefix="body",
        )
    tree_joint_name_by_group: dict[str, str] = {}
    for group_id, edge in parent_edge.items():
        tree_joint_name_by_group[group_id] = names.claim(
            "joint",
            "joint_" + str(edge["joint"]["joint_id"]),
            identity=str(edge["joint"]["joint_id"]),
            prefix="joint",
        )

    angle_terms_by_group: dict[str, dict[str, float]] = {root_group: {}}
    for group_id in parent_group:
        if group_id == root_group:
            continue
        parent = parent_group[group_id]
        if parent is None or parent not in angle_terms_by_group:
            raise ValueError(
                f"group {group_id!r} has no resolved parent angle expression"
            )
        terms = dict(angle_terms_by_group[parent])
        terms[tree_joint_name_by_group[group_id]] = 1.0
        angle_terms_by_group[group_id] = terms

    tree_edge_ids = {id(edge) for edge in parent_edge.values()}
    non_tree_movable_edges = [
        edge for edge in movable_edges if id(edge) not in tree_edge_ids
    ]

    def relative_angle_terms(
        edge: Mapping[str, Any], group_id: str
    ) -> dict[str, float]:
        first_group = str(edge["a_group"])
        second_group = str(edge["b_group"])
        if group_id == second_group:
            return _subtracted_terms(
                angle_terms_by_group[second_group],
                angle_terms_by_group[first_group],
            )
        if group_id == first_group:
            return _subtracted_terms(
                angle_terms_by_group[first_group],
                angle_terms_by_group[second_group],
            )
        raise ValueError(
            f"movable support {edge['joint']['joint_id']!r} does not attach "
            f"to group {group_id!r}"
        )

    def support_edge(
        _connector_snapshot_id: str, group_id: str
    ) -> dict[str, Any] | None:
        """Return the tree edge that carries a group's generalized angle.

        A connector may participate in several movable constraints, such as a
        shaft revolute and a nested bearing's internal revolute. The spanning
        tree, rather than connector identity, determines the group's angle.
        """

        if group_id == root_group:
            return None
        try:
            return parent_edge[group_id]
        except KeyError as exc:
            raise ValueError(
                f"group {group_id!r} has no spanning-tree support edge"
            ) from exc


    part_materials = _part_materials(units)
    mesh_by_definition: dict[str, str] = {}
    density_by_definition: dict[str, float] = {}
    default_density_count = 0
    for definition_id, (part, _unused_density, _unused_default) in sorted(
        part_materials.items()
    ):
        density, used_default = _density_kg_m3(
            part.material,
            default_density_kg_m3=default_density_kg_m3,
        )
        density_by_definition[definition_id] = density
        default_density_count += int(used_default)
        mesh_name = names.claim(
            "mesh",
            "mesh_" + definition_id,
            identity=definition_id,
            prefix="mesh",
        )
        mesh_path = mesh_root / f"{mesh_name}.obj"
        _write_obj(
            mesh_path,
            part.body,
            linear_deflection=float(linear_deflection),
            angular_deflection_degrees=float(angular_deflection_degrees),
        )
        mesh_by_definition[definition_id] = mesh_name

    entity_documents = _entity_documents(scene_package)
    mesh_asset_elements: list[ET.Element] = []
    for definition_id, mesh_name in sorted(mesh_by_definition.items()):
        mesh_asset_elements.append(
            ET.Element(
                "mesh",
                {
                    "name": mesh_name,
                    "file": os.path.relpath(
                        mesh_root / f"{mesh_name}.obj",
                        start=destination.parent,
                    ),
                    "scale": "0.001 0.001 0.001",
                },
            )
        )

    root_xml = ET.Element(
        "mujoco", {"model": str(package.root_definition.definition_id)}
    )
    ET.SubElement(root_xml, "compiler", {"angle": "radian", "coordinate": "local"})
    ET.SubElement(root_xml, "option", {"gravity": "0 0 -9.81"})
    asset_xml = ET.SubElement(root_xml, "asset")
    for element in mesh_asset_elements:
        asset_xml.append(element)
    world_xml = ET.SubElement(root_xml, "worldbody")

    group_children: dict[str, list[str]] = defaultdict(list)
    for group_id, parent in parent_group.items():
        if parent is not None:
            group_children[parent].append(group_id)

    group_body_frame: dict[str, Placement] = {
        root_group: Placement((0.0, 0.0, 0.0)),
        **{
            group_id: world[group_representative[group_id]]
            for group_id in groups
            if group_id != root_group
        },
    }
    body_nodes: dict[str, ET.Element] = {root_group: world_xml}

    def relative_to_group(group_id: str, node_id: str) -> Placement:
        return relative_placement(group_body_frame[group_id], world[node_id])

    site_count = 0
    geom_count = 0
    site_records: list[dict[str, Any]] = []

    def append_group_content(group_id: str, parent_xml: ET.Element) -> None:
        nonlocal site_count, geom_count
        body_frame = group_body_frame[group_id]
        for node_id in sorted(groups[group_id]):
            node = nodes[node_id]
            definition_id = str(node["definition_id"])
            mesh_name = mesh_by_definition.get(definition_id)
            if mesh_name is not None:
                local = relative_to_group(group_id, node_id)
                if node.get("parent_node_id") == root_node_id and node.get(
                    "component_id"
                ):
                    semantic_id = str(node["component_id"])
                else:
                    semantic_id = f"geom_{node_id}"
                geom_name = names.claim(
                    "geom",
                    semantic_id,
                    identity=node_id,
                    prefix="geom",
                )
                attrs = {
                    "name": geom_name,
                    "type": "mesh",
                    "mesh": mesh_name,
                    "density": _fmt(density_by_definition[definition_id]),
                    "contype": "1",
                    "conaffinity": "1",
                    **_placement_attributes(local, scale_length=True),
                }
                ET.SubElement(parent_xml, "geom", attrs)
                geom_count += 1
            if node["entity_asset_id"] is None:
                continue
            document = entity_documents[definition_id]
            for entity in document["entities"]:
                tags = [
                    str(tag)
                    for tag in entity.get("tags", [])
                    if str(tag).startswith("interface.")
                ]
                if not tags:
                    continue
                props = entity.get("properties", {})
                frame_payload = props.get("connector_frame")
                if frame_payload is None:
                    origin = tuple(
                        float(value) for value in props.get("centroid", [0.0, 0.0, 0.0])
                    )
                    entity_frame = Placement(origin)
                else:
                    entity_frame = _placement(frame_payload)
                site_world = world[node_id].compose(entity_frame)
                local = relative_placement(body_frame, site_world)
                for tag in tags:
                    site_identity = f"entity:{node_id}:{entity['entity_id']}:{tag}"
                    site_name = names.claim(
                        "site",
                        f"site_{node_id}_{tag}",
                        identity=site_identity,
                        prefix="site",
                    )
                    ET.SubElement(
                        parent_xml,
                        "site",
                        {
                            "name": site_name,
                            "size": "0.0008",
                            "type": "sphere",
                            **_placement_attributes(local, scale_length=True),
                        },
                    )
                    site_records.append(
                        {
                            "name": site_name,
                            "tag": tag,
                            "node_id": node_id,
                            "entity_id": entity["entity_id"],
                            "topo_id": entity["topo_id"],
                        }
                    )
                    site_count += 1

    def append_group_tree(group_id: str, parent_xml: ET.Element) -> None:
        for child_group in sorted(
            group_children[group_id], key=lambda item: body_name_by_group[item]
        ):
            child_frame = group_body_frame[child_group]
            parent_frame = group_body_frame[group_id]
            local = relative_placement(parent_frame, child_frame)
            body_xml = ET.SubElement(
                parent_xml,
                "body",
                {
                    "name": body_name_by_group[child_group],
                    **_placement_attributes(local, scale_length=True),
                },
            )
            body_nodes[child_group] = body_xml
            edge = parent_edge[child_group]
            joint = edge["joint"]
            connector = edge["connector_a"]
            connector_frame = _placement(connector["local_frame"])
            joint_world = world[str(connector["node_id"])].compose(connector_frame)
            joint_local = relative_placement(child_frame, joint_world)
            joint_axis_world = world[str(connector["node_id"])].transform_vector(
                connector_frame.z_axis
            )
            axis = _inverse_vector(child_frame, joint_axis_world)
            joint_attrs = {
                "name": tree_joint_name_by_group[child_group],
                "type": "hinge" if joint["joint_type"] == "revolute" else "slide",
                "pos": _fmt_vec(tuple(value * 0.001 for value in joint_local.origin)),
                "axis": _fmt_vec(axis),
            }
            limits = joint.get("limits")
            if limits is not None:
                limit_key = (
                    "angle_limit"
                    if joint["joint_type"] == "revolute"
                    else "distance_limit"
                )
                scalar_limit = limits.get(limit_key) or limits
                lower = float(scalar_limit.get("lower_value", 0.0))
                upper = float(scalar_limit.get("upper_value", 0.0))
                if joint["joint_type"] == "revolute":
                    lower = lower * 3.141592653589793 / 180.0
                    upper = upper * 3.141592653589793 / 180.0
                else:
                    lower, upper = lower * 0.001, upper * 0.001
                joint_attrs.update(
                    {"limited": "true", "range": f"{_fmt(lower)} {_fmt(upper)}"}
                )
            ET.SubElement(body_xml, "joint", joint_attrs)
            append_group_content(child_group, body_xml)
            append_group_tree(child_group, body_xml)

    append_group_content(root_group, world_xml)
    append_group_tree(root_group, world_xml)

    public_connectors = [
        connector
        for connector in connector_records
        if str(connector["node_id"]) == root_node_id
    ]
    for connector in public_connectors:
        connector_id = str(connector["connector_id"])
        leaf = leaf_connector(connector)
        leaf_node_id = str(leaf["node_id"])
        group_id = group_for_node[leaf_node_id]
        frame_world = world[str(connector["node_id"])].compose(
            _placement(connector["local_frame"])
        )
        local = relative_placement(group_body_frame[group_id], frame_world)
        site_name = names.claim(
            "site",
            connector_id,
            identity=f"connector:{connector['connector_snapshot_id']}",
            prefix="site",
        )
        ET.SubElement(
            body_nodes[group_id],
            "site",
            {
                "name": site_name,
                "size": "0.0012",
                "type": "sphere",
                **_placement_attributes(local, scale_length=True),
            },
        )
        site_records.append(
            {
                "name": site_name,
                "connector_id": connector_id,
                "connector_snapshot_id": connector["connector_snapshot_id"],
                "node_id": connector["node_id"],
                "attached_group": group_id,
            }
        )
        site_count += 1

    joint_names = sorted(tree_joint_name_by_group.values())
    joint_index = {name: index for index, name in enumerate(joint_names)}
    candidate_equalities: list[dict[str, Any]] = []
    for edge in equality_edges:
        joint = edge["joint"]
        kind = str(joint["joint_type"])
        parameters = dict(joint.get("parameters") or {})
        endpoint_terms: list[dict[str, float]] = []
        for side in ("a", "b"):
            connector = edge[f"connector_{side}"]
            group_id = group_for_node[str(edge[side])]
            support = support_edge(str(connector["connector_snapshot_id"]), group_id)
            if support is None:
                if group_id != root_group:
                    raise ValueError(
                        f"coupling {joint['joint_id']!r} endpoint {side} has no movable support"
                    )
                endpoint_terms.append({})
            else:
                endpoint_terms.append(relative_angle_terms(support, group_id))
        first_terms, second_terms = endpoint_terms
        coefficients: dict[str, float] = {}
        if kind == "gear":
            _add_scaled_terms(
                coefficients, first_terms, float(parameters["pitch_radius_a"])
            )
            _add_scaled_terms(
                coefficients, second_terms, float(parameters["pitch_radius_b"])
            )
        elif kind == "belt":
            _add_scaled_terms(
                coefficients, first_terms, float(parameters["pulley_radius_a"])
            )
            _add_scaled_terms(
                coefficients, second_terms, -float(parameters["pulley_radius_b"])
            )
        else:
            _add_scaled_terms(coefficients, first_terms, 1.0)
            _add_scaled_terms(
                coefficients,
                second_terms,
                float(parameters["pitch_radius"]) * 0.001,
            )
        coefficients = {
            name: value for name, value in coefficients.items() if abs(value) > 1.0e-12
        }
        if not coefficients:
            raise ValueError(
                f"coupling {joint['joint_id']!r} produced an empty equation"
            )
        row = np.zeros(len(joint_names), dtype=float)
        for name, coefficient in coefficients.items():
            row[joint_index[name]] = coefficient
        candidate_equalities.append(
            {
                "joint": joint,
                "coefficients": coefficients,
                "row": row,
                "reference_phase": float(parameters.get("phase_offset", 0.0)),
            }
        )

    independent_equalities: list[dict[str, Any]] = []
    current_rows = np.empty((0, len(joint_names)), dtype=float)
    current_rank = 0
    equality_records: list[dict[str, Any]] = []
    for candidate in candidate_equalities:
        trial = np.vstack((current_rows, candidate["row"]))
        trial_rank = int(np.linalg.matrix_rank(trial, tol=1.0e-10))
        independent = trial_rank > current_rank
        record = {
            "equality_id": str(candidate["joint"]["joint_id"]),
            "joint_type": str(candidate["joint"]["joint_type"]),
            "coefficients": dict(sorted(candidate["coefficients"].items())),
            "reference_phase_source_units": candidate["reference_phase"],
            "independent": independent,
        }
        equality_records.append(record)
        if independent:
            independent_equalities.append({**candidate, "record": record})
            current_rows = trial
            current_rank = trial_rank

    tendon_xml = ET.SubElement(root_xml, "tendon")
    equality_xml = ET.SubElement(root_xml, "equality")
    for candidate in independent_equalities:
        joint = candidate["joint"]
        joint_id = str(joint["joint_id"])
        tendon_name = names.claim(
            "tendon",
            "coupling_" + joint_id,
            identity=joint_id,
            prefix="coupling",
        )
        fixed_xml = ET.SubElement(tendon_xml, "fixed", {"name": tendon_name})
        for name, coefficient in sorted(candidate["coefficients"].items()):
            ET.SubElement(
                fixed_xml,
                "joint",
                {"joint": name, "coef": _fmt(coefficient)},
            )
        equality_name = names.claim(
            "equality",
            "equality_" + joint_id,
            identity=joint_id,
            prefix="equality",
        )
        ET.SubElement(
            equality_xml,
            "tendon",
            {
                "name": equality_name,
                "tendon1": tendon_name,
                "polycoef": "0 0 0 0 0",
            },
        )
        candidate["record"].update({"name": equality_name, "tendon": tendon_name})
    # Loop-closing movable joints cannot be tree hinges (their groups are
    # already connected through the tree) and their closure condition is not
    # a linear angle equation; emit MuJoCo point-on-point equality/connect
    # constraints between closure sites on both endpoint groups.
    closure_records: list[dict[str, Any]] = []
    for edge in non_tree_movable_edges:
        joint = edge["joint"]
        joint_id = str(joint["joint_id"])
        record = {
            "joint_id": joint_id,
            "joint_type": str(joint["joint_type"]),
        }
        site_specs = []
        for side in ("a", "b"):
            connector = edge[f"connector_{side}"]
            group_id = group_for_node[str(edge[side])]
            connector_world = world[str(connector["node_id"])].compose(
                _placement(connector["local_frame"])
            )
            local = relative_placement(
                group_body_frame[group_id], connector_world
            )
            site_name = names.claim(
                "site",
                f"closure_{side}_" + joint_id,
                identity=f"closure:{joint_id}:{side}",
                prefix="closure",
            )
            ET.SubElement(
                body_nodes[group_id],
                "site",
                {
                    "name": site_name,
                    "size": "0.0012",
                    "type": "sphere",
                    **_placement_attributes(local, scale_length=True),
                },
            )
            site_specs.append({"name": site_name, "group": group_id})
        equality_name = names.claim(
            "equality",
            "closure_" + joint_id,
            identity=joint_id,
            prefix="closure",
        )
        ET.SubElement(
            equality_xml,
            "connect",
            {
                "name": equality_name,
                "site1": site_specs[0]["name"],
                "site2": site_specs[1]["name"],
            },
        )
        record.update(
            {
                "name": equality_name,
                "sites": site_specs,
            }
        )
        closure_records.append(record)
    if not independent_equalities and not closure_records:
        root_xml.remove(tendon_xml)
        root_xml.remove(equality_xml)

    ET.indent(root_xml, space="  ")
    tree = ET.ElementTree(root_xml)
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    if destination.stat().st_size <= 0:
        raise RuntimeError("MJCF writer produced an empty XML file")

    group_records = [
        {
            "group_id": group_id,
            "members": sorted(members),
            "grounded": group_id == root_group,
            "representative": group_representative[group_id],
            "body_name": (
                None if group_id == root_group else body_name_by_group[group_id]
            ),
            "parent_group": parent_group[group_id],
            "tree_joint": (
                None if group_id == root_group else tree_joint_name_by_group[group_id]
            ),
        }
        for group_id, members in sorted(groups.items())
    ]
    mapping = {
        "schema_version": "1.0",
        "root_definition_id": package.root_definition.definition_id,
        "units": {"source": "mm", "mjcf_length": "m", "mjcf_angle": "radian"},
        "grounded_group_id": root_group,
        "groups": group_records,
        "pruned_structure_nodes": pruned_structure_nodes,
        "rigid_edges": rigid_edges,
        "tree_joints": [
            {
                "joint_id": str(edge["joint"]["joint_id"]),
                "group": group_id,
                "parent_group": parent_group[group_id],
                "joint_name": tree_joint_name_by_group[group_id],
            }
            for group_id, edge in sorted(parent_edge.items())
        ],
        "redundant_movable_joints": [],
        "closures": closure_records,
        "equalities": equality_records,
        "sites": site_records,
        "meshes": {
            definition_id: name
            for definition_id, name in sorted(mesh_by_definition.items())
        },
        "default_density_count": default_density_count,
    }
    decision_path.write_text(
        json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    limitations = (
        "Mesh geoms are generated from BREP tessellation and scaled from mm to m.",
        "MuJoCo mesh collision uses its supported mesh collision representation; no convex decomposition is attempted.",
        "Public connector declarations resolve endpoint ownership to leaf connectors; only explicit fixed constraints create rigid groups.",
        "Gear, belt, and rack-pinion relations constrain reference-pose increments through independent fixed tendons.",
        "Loop-closing revolute/prismatic joints become equality/connect constraints between closure sites.",
    )
    return ProductMJCFExportReport(
        output_path=destination,
        mapping_path=decision_path,
        mesh_directory=mesh_root,
        root_definition_id=package.root_definition.definition_id,
        mesh_count=len(mesh_by_definition),
        body_count=len(body_name_by_group),
        joint_count=len(tree_joint_name_by_group),
        equality_count=len(independent_equalities),
        closure_count=len(closure_records),
        grounded_group_count=1,
        site_count=site_count,
        default_density_count=default_density_count,
        limitations=limitations,
    )


__all__ = ["ProductMJCFExportReport", "export_product_package_to_mjcf"]
