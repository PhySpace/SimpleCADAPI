"""OCP-native core class definitions for the SimpleCAD API."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union, cast

import numpy as np
from OCP.TopAbs import (
    TopAbs_COMPOUND,
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_VERTEX,
    TopAbs_WIRE,
)
from OCP.TopoDS import TopoDS, TopoDS_Shape

from ._internal.vendor_warning_filters import suppress_vendor_deprecation_warnings
from .errors import SimpleCADError, raise_harness_error
from .kernel.ocp_cast import (
    as_compound,
    as_edge,
    as_face,
    as_shell,
    as_solid,
    as_vertex,
    as_wire,
    shape_type_name,
)
from .kernel.ocp_booleans import solids_of
from .kernel.ocp_mesh import shell_is_closed
from .kernel.ocp_properties import (
    Vec3,
    center_of_mass,
    face_normal_at,
    linear_length,
    surface_area,
    volume,
)
from .kernel.ocp_topology import (
    edges_of,
    faces_of,
    inner_wires_of,
    is_wire_closed,
    outer_wire_of,
    vertex_point,
    vertices_of,
)
from .kernel.ocp_surfaces import free_boundaries
from .topology.tagging import (
    LineagePolicy,
    TagAttachment,
    TagBinding,
    TagEvidence,
    TagLineageWitness,
    TagProducer,
    TagProducerKind,
    TagScope,
    TopologyPropagation,
    UnsupportedQueryCapabilityError,
    internal_tag_binding,
    legacy_tag_binding,
    lineage_policy_allows,
    normalize_tag,
    normalize_tag_scope,
    user_tag_binding,
)

suppress_vendor_deprecation_warnings()


def _safe_shape_hash(shape: Any) -> int:
    try:
        return int(shape.HashCode(1000000))
    except Exception:
        return int(hash(shape))


@dataclass
class _TopoEntity:
    kind: str
    topo_id: str
    representative: Any
    tags: Set[str] = field(default_factory=set)
    tag_bindings: List[TagBinding] = field(default_factory=list)
    tag_lineage: List[TagLineageWitness] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    runtime: Dict[str, Any] = field(default_factory=dict)
    wrappers: List[Any] = field(default_factory=list)
    incident_face_ids: Set[str] = field(default_factory=set)
    incident_edge_ids: Set[str] = field(default_factory=set)


class _TopologyEntityCache:
    def __init__(self) -> None:
        self._buckets: Dict[Tuple[str, int], List[_TopoEntity]] = {}
        self._counters: Dict[str, int] = {}
        self._entities_by_id: Dict[str, _TopoEntity] = {}

    def get(self, kind: str, shape: Any) -> _TopoEntity:
        key = (kind, _safe_shape_hash(shape))
        bucket = self._buckets.setdefault(key, [])
        for entity in bucket:
            try:
                if entity.representative.IsSame(shape):
                    return entity
            except Exception:
                pass

        idx = self._counters.get(kind, 0)
        self._counters[kind] = idx + 1
        entity = _TopoEntity(kind=kind, topo_id=f"{kind}_{idx}", representative=shape)
        bucket.append(entity)
        self._entities_by_id[entity.topo_id] = entity
        return entity

    def wrappers_for(self, topo_id: str) -> List[Any]:
        entity = self._entities_by_id.get(topo_id)
        return list(entity.wrappers) if entity is not None else []

    def entities(self, kind: Optional[str] = None) -> List[_TopoEntity]:
        if kind is None:
            return list(self._entities_by_id.values())
        return [entity for entity in self._entities_by_id.values() if entity.kind == kind]


def _copy_entity_state(source: _TopoEntity, target: _TopoEntity) -> None:
    target.tags.clear()
    target.tags.update(source.tags)
    target.tag_bindings[:] = list(source.tag_bindings)
    target.tag_lineage[:] = list(source.tag_lineage)
    target.metadata.clear()
    target.metadata.update(deepcopy(source.metadata))
    target.runtime.clear()
    target.runtime.update(deepcopy(source.runtime))
    target.incident_face_ids.clear()
    target.incident_face_ids.update(source.incident_face_ids)
    target.incident_edge_ids.clear()
    target.incident_edge_ids.update(source.incident_edge_ids)


class CoordinateSystem:
    """Three-dimensional coordinate system.

    SimpleCAD uses a right-handed Z-up coordinate system with the origin at
    (0, 0, 0): X forward, Y right, Z up.
    """

    def __init__(
        self,
        origin: Tuple[float, float, float] = (0, 0, 0),
        x_axis: Tuple[float, float, float] = (1, 0, 0),
        y_axis: Tuple[float, float, float] = (0, 1, 0),
    ):
        try:
            self.origin = np.array(origin, dtype=float)
            self.x_axis = self._normalize(x_axis)
            self.y_axis = self._normalize(y_axis)
            self.z_axis = self._normalize(np.cross(self.x_axis, self.y_axis))
        except Exception as e:
            raise_harness_error(
                operation="CoordinateSystem.__init__",
                what_happened="Failed to create a coordinate system.",
                possible_causes=[
                    "One of the origin or axis values is not a valid 3D numeric vector.",
                    "One of the axis vectors is zero-length or cannot be normalized.",
                    "The axis inputs are malformed or contain non-numeric values.",
                ],
                how_to_fix=[
                    "Pass origin, x_axis, and y_axis as 3-element numeric tuples or arrays.",
                    "Make sure x_axis and y_axis are non-zero vectors.",
                    "If you build axes dynamically, print the vectors before constructing the coordinate system.",
                ],
                error=e,
            )

    def _normalize(self, vector) -> np.ndarray:
        v = np.array(vector, dtype=float)
        norm = np.linalg.norm(v)
        if norm == 0:
            raise_harness_error(
                operation="CoordinateSystem._normalize",
                what_happened="A zero-length vector cannot be normalized.",
                possible_causes=[
                    "The input vector is exactly (0, 0, 0).",
                    "The input values collapsed to zero after numeric conversion.",
                ],
                how_to_fix=[
                    "Provide a non-zero direction vector.",
                    "Check upstream calculations that produce this vector.",
                ],
                technical_details=f"vector={tuple(v.tolist())}",
            )
        return v / norm

    def transform_point(self, point: np.ndarray) -> np.ndarray:
        try:
            local_point = np.asarray(point, dtype=float)
            if local_point.shape != (3,):
                raise_harness_error(
                    operation="CoordinateSystem.transform_point",
                    what_happened="The point could not be interpreted as a 3D coordinate.",
                    possible_causes=[
                        "The point does not contain exactly three numeric components.",
                        "The point contains NaN or non-numeric values.",
                    ],
                    how_to_fix=[
                        "Pass the point as a 3-element tuple, list, or NumPy array.",
                        "Validate the point values before calling transform_point().",
                    ],
                    technical_details=f"point_shape={local_point.shape}",
                )
            if not np.all(np.isfinite(local_point)):
                raise_harness_error(
                    operation="CoordinateSystem.transform_point",
                    what_happened="The point contains non-finite numeric values.",
                    possible_causes=[
                        "A previous computation produced NaN or infinity.",
                        "The point was assembled from invalid expression results.",
                    ],
                    how_to_fix=[
                        "Inspect the upstream values used to build the point.",
                        "Replace NaN or infinity with finite numeric coordinates before calling this API.",
                    ],
                    technical_details=f"point={tuple(local_point.tolist())}",
                )
            return (
                self.origin
                + local_point[0] * self.x_axis
                + local_point[1] * self.y_axis
                + local_point[2] * self.z_axis
            )
        except Exception as e:
            raise_harness_error(
                operation="CoordinateSystem.transform_point",
                what_happened="Failed to transform the point into global coordinates.",
                possible_causes=[
                    "The point is not a valid finite 3D vector.",
                    "The coordinate system axes are invalid or inconsistent.",
                ],
                how_to_fix=[
                    "Pass a finite 3D point.",
                    "Validate the coordinate system before transforming points.",
                ],
                error=e,
            )

    def transform_vector(self, vector: np.ndarray) -> np.ndarray:
        try:
            v = np.array(vector, dtype=float)
            if v.shape != (3,):
                raise_harness_error(
                    operation="CoordinateSystem.transform_vector",
                    what_happened="The vector could not be interpreted as a 3D direction.",
                    possible_causes=[
                        "The input does not contain exactly three numeric components.",
                        "The input was passed as a malformed nested structure.",
                    ],
                    how_to_fix=[
                        "Pass the vector as a 3-element tuple, list, or NumPy array.",
                        "Validate the vector shape before calling transform_vector().",
                    ],
                    technical_details=f"vector_shape={v.shape}",
                )
            if not np.all(np.isfinite(v)):
                raise_harness_error(
                    operation="CoordinateSystem.transform_vector",
                    what_happened="The vector contains non-finite numeric values.",
                    possible_causes=[
                        "A previous computation produced NaN or infinity.",
                        "The direction vector was derived from invalid geometry.",
                    ],
                    how_to_fix=[
                        "Inspect the upstream direction calculation.",
                        "Ensure all vector components are finite numbers before calling this API.",
                    ],
                    technical_details=f"vector={tuple(v.tolist())}",
                )
            return v[0] * self.x_axis + v[1] * self.y_axis + v[2] * self.z_axis
        except Exception as e:
            raise_harness_error(
                operation="CoordinateSystem.transform_vector",
                what_happened="Failed to transform the vector into global coordinates.",
                possible_causes=[
                    "The vector is not a valid finite 3D direction.",
                    "The coordinate system axes are invalid or inconsistent.",
                ],
                how_to_fix=[
                    "Pass a finite 3D direction vector.",
                    "Validate the coordinate system before transforming vectors.",
                ],
                error=e,
            )

    def __str__(self) -> str:
        return self._format_string(indent=0)

    def __repr__(self) -> str:
        return f"CoordinateSystem(origin={tuple(self.origin)}, x_axis={tuple(self.x_axis)}, y_axis={tuple(self.y_axis)})"

    def _format_string(self, indent: int = 0) -> str:
        spaces = "  " * indent
        result = []
        result.append(f"{spaces}CoordinateSystem:")
        result.append(f"{spaces}  origin: [{self.origin[0]:.3f}, {self.origin[1]:.3f}, {self.origin[2]:.3f}]")
        result.append(f"{spaces}  x_axis: [{self.x_axis[0]:.3f}, {self.x_axis[1]:.3f}, {self.x_axis[2]:.3f}]")
        result.append(f"{spaces}  y_axis: [{self.y_axis[0]:.3f}, {self.y_axis[1]:.3f}, {self.y_axis[2]:.3f}]")
        result.append(f"{spaces}  z_axis: [{self.z_axis[0]:.3f}, {self.z_axis[1]:.3f}, {self.z_axis[2]:.3f}]")
        return "\n".join(result)


WORLD_CS = CoordinateSystem()


class SimpleWorkplane:
    """Workplane context manager defining a local coordinate system."""

    def __init__(
        self,
        origin: Tuple[float, float, float] = (0, 0, 0),
        normal: Tuple[float, float, float] = (0, 0, 1),
        x_dir: Tuple[float, float, float] = (1, 0, 0),
    ):
        current_cs = get_current_cs()
        global_origin = current_cs.transform_point(np.array(origin))
        global_x_dir = current_cs.transform_vector(np.array(x_dir))
        global_normal = current_cs.transform_vector(np.array(normal))
        global_normal = global_normal / np.linalg.norm(global_normal)
        global_y_dir = np.cross(global_normal, global_x_dir)
        y_norm = np.linalg.norm(global_y_dir)
        if y_norm < 1e-10:
            temp_x = np.array([1, 0, 0]) if abs(global_normal[0]) < 0.9 else np.array([0, 1, 0])
            global_y_dir = np.cross(global_normal, temp_x)
            global_y_dir = global_y_dir / np.linalg.norm(global_y_dir)
            global_x_dir = np.cross(global_y_dir, global_normal)
            global_x_dir = global_x_dir / np.linalg.norm(global_x_dir)
        else:
            global_y_dir = global_y_dir / y_norm
            global_x_dir = np.cross(global_y_dir, global_normal)
            global_x_dir = global_x_dir / np.linalg.norm(global_x_dir)
        self.cs = CoordinateSystem(tuple(global_origin), tuple(global_x_dir), tuple(global_y_dir))
        self._token: Optional[Token[Tuple[CoordinateSystem, ...]]] = None

    def __enter__(self):
        stack = _current_cs_stack.get()
        self._token = _current_cs_stack.set((*stack, self.cs))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._token is not None:
            _current_cs_stack.reset(self._token)
            self._token = None

    def __str__(self) -> str:
        return self._format_string(indent=0)

    def __repr__(self) -> str:
        return f"SimpleWorkplane(origin={tuple(self.cs.origin)}, normal={tuple(self.cs.z_axis)})"

    def _format_string(self, indent: int = 0, show_coordinate_system: bool = True) -> str:
        spaces = "  " * indent
        result = [f"{spaces}SimpleWorkplane:"]
        if show_coordinate_system:
            result.append(f"{spaces}  coordinate_system:")
            result.append(self.cs._format_string(indent + 2))
        return "\n".join(result)


_current_cs_stack: ContextVar[Tuple[CoordinateSystem, ...]] = ContextVar(
    "simplecadapi_current_cs_stack", default=(WORLD_CS,)
)


def get_current_cs() -> CoordinateSystem:
    return _current_cs_stack.get()[-1]


def _coordinate_system_from_context(context: Dict[str, Any]) -> CoordinateSystem:
    origin = context.get("origin", (0.0, 0.0, 0.0))
    x_axis = context.get("x_axis", (1.0, 0.0, 0.0))
    y_axis = context.get("y_axis", (0.0, 1.0, 0.0))
    return CoordinateSystem(
        cast(Tuple[float, float, float], tuple(float(v) for v in origin)),
        cast(Tuple[float, float, float], tuple(float(v) for v in x_axis)),
        cast(Tuple[float, float, float], tuple(float(v) for v in y_axis)),
    )


@contextmanager
def use_coordinate_system(
    cs_or_context: Union[CoordinateSystem, Dict[str, Any]]
):
    cs = (
        cs_or_context
        if isinstance(cs_or_context, CoordinateSystem)
        else _coordinate_system_from_context(cs_or_context)
    )
    stack = _current_cs_stack.get()
    token = _current_cs_stack.set((*stack, cs))
    try:
        yield
    finally:
        _current_cs_stack.reset(token)


class TaggedMixin:
    """Tag mixin that provides tagging support for geometry objects."""

    def __init__(self, entity: Optional[_TopoEntity] = None):
        self._entity = entity
        if entity is None:
            self._standalone_tag_cache: Set[str] = set()
            self._standalone_tag_bindings: List[TagBinding] = []
            self._standalone_tag_lineage: List[TagLineageWitness] = []
            self._standalone_metadata: Dict[str, Any] = {}
            self._standalone_runtime: Dict[str, Any] = {}
        else:
            entity.wrappers.append(self)

    @property
    def _tag_cache(self) -> Set[str]:
        entity = getattr(self, "_entity", None)
        if entity is not None:
            return entity.tags
        return self._standalone_tag_cache

    @_tag_cache.setter
    def _tag_cache(self, values: Iterable[str]) -> None:
        replacement = set(values)
        target = self._tag_cache
        target.clear()
        target.update(replacement)

    @property
    def _tag_bindings(self) -> List[TagBinding]:
        entity = getattr(self, "_entity", None)
        if entity is not None:
            return entity.tag_bindings
        return self._standalone_tag_bindings

    @_tag_bindings.setter
    def _tag_bindings(self, values: Iterable[TagBinding]) -> None:
        replacement = list(values)
        self._tag_bindings[:] = replacement

    @property
    def _tag_lineage(self) -> List[TagLineageWitness]:
        entity = getattr(self, "_entity", None)
        if entity is not None:
            return entity.tag_lineage
        return self._standalone_tag_lineage

    @_tag_lineage.setter
    def _tag_lineage(self, values: Iterable[TagLineageWitness]) -> None:
        replacement = list(values)
        self._tag_lineage[:] = replacement

    @property
    def _metadata(self) -> Dict[str, Any]:
        entity = getattr(self, "_entity", None)
        if entity is not None:
            return entity.metadata
        return self._standalone_metadata

    @_metadata.setter
    def _metadata(self, values: Dict[str, Any]) -> None:
        replacement = dict(values)
        target = self._metadata
        target.clear()
        target.update(replacement)

    @property
    def _runtime(self) -> Dict[str, Any]:
        entity = getattr(self, "_entity", None)
        if entity is not None:
            return entity.runtime
        return self._standalone_runtime

    @_runtime.setter
    def _runtime(self, values: Dict[str, Any]) -> None:
        replacement = dict(values)
        target = self._runtime
        target.clear()
        target.update(replacement)

    @property
    def _tags(self) -> Set[str]:
        """Compatibility cache; TagBinding objects are canonical truth."""

        return self._tag_cache

    @_tags.setter
    def _tags(self, values: Iterable[str]) -> None:
        if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
            raise TypeError("_tags compatibility cache must be assigned an iterable")
        imported = []
        for value in values:
            imported.append(
                legacy_tag_binding(
                    normalize_tag(value, strict=True),
                    diagnostic="Imported from a direct legacy _tags assignment.",
                )
            )
        if hasattr(self, "_tag_bindings"):
            self._tag_bindings[:] = imported
        else:
            self._tag_bindings = imported
        if hasattr(self, "_tag_lineage"):
            self._tag_lineage[:] = []
        else:
            self._tag_lineage = []
        cache = getattr(self, "_tag_cache", None)
        if cache is None:
            self._tag_cache = set()
        self._refresh_tag_cache()

    @property
    def topo_id(self) -> str:
        entity = getattr(self, "_entity", None)
        if entity is not None:
            return entity.topo_id
        return f"object_{id(self)}"

    def same_topology(self, other: Any) -> bool:
        return getattr(other, "topo_id", None) == self.topo_id

    def _add_tag(self, tag: str) -> None:
        if not isinstance(tag, str):
            raise TypeError("标签必须是字符串类型")
        self._add_tag_binding(internal_tag_binding(normalize_tag(tag, strict=True)))

    def _add_tag_binding(self, binding: TagBinding) -> None:
        if not isinstance(binding, TagBinding):
            raise TypeError("binding must be a TagBinding")
        if not any(item.binding_id == binding.binding_id for item in self._tag_bindings):
            self._tag_bindings.append(binding)
        self._refresh_tag_cache(
            recursive=binding.propagation.topology == TopologyPropagation.DOWNWARD
        )

    def _add_tag_lineage(
        self,
        binding: TagBinding,
        *,
        derivation: str,
        source_topo_id: str,
        evidence: TagEvidence,
        coverage: str = "complete",
    ) -> None:
        witness = TagLineageWitness(
            binding=binding,
            derivation=derivation,
            source_topo_id=str(source_topo_id),
            target_topo_id=self.topo_id,
            evidence=evidence,
            coverage=coverage,
        )
        marker = (
            witness.binding.binding_id,
            witness.derivation,
            witness.source_topo_id,
            witness.target_topo_id,
        )
        if not any(
            (
                item.binding.binding_id,
                item.derivation,
                item.source_topo_id,
                item.target_topo_id,
            )
            == marker
            for item in self._tag_lineage
        ):
            self._tag_lineage.append(witness)

    def _copy_tag_state_from(self, source: "TaggedMixin") -> None:
        if not isinstance(source, TaggedMixin):
            raise TypeError("source must be a TaggedMixin")
        self._tag_bindings[:] = list(source._tag_bindings)
        self._tag_lineage[:] = list(source._tag_lineage)
        self._refresh_tag_cache(recursive=True)

    def _copy_semantic_state_from(self, source: "TaggedMixin") -> None:
        if not isinstance(source, TaggedMixin):
            raise TypeError("source must be a TaggedMixin")
        self._tag_bindings[:] = list(source._tag_bindings)
        self._tag_lineage[:] = list(source._tag_lineage)
        self._metadata = deepcopy(
            {
                key: value
                for key, value in source._metadata.items()
                if key not in {"graph", "topo_ref"}
            }
        )
        self._runtime = deepcopy(
            {
                key: value
                for key, value in source._runtime.items()
                if not key.startswith(("graph.", "topo.", "mesh."))
            }
        )
        self._refresh_tag_cache(recursive=True)

    def _replace_local_tag_bindings(self, bindings: Iterable[TagBinding]) -> None:
        retained = [
            binding
            for binding in self._tag_bindings
            if binding.attachment != TagAttachment.LOCAL
        ]
        replacements = list(bindings)
        if not all(isinstance(binding, TagBinding) for binding in replacements):
            raise TypeError("bindings must contain only TagBinding objects")
        self._tag_bindings[:] = [*retained, *replacements]
        self._refresh_tag_cache(recursive=True)

    def _refresh_tag_cache(
        self, *, recursive: bool = False, _visited: Optional[Set[int]] = None
    ) -> None:
        visited = _visited if _visited is not None else set()
        marker = id(self)
        if marker in visited:
            return
        visited.add(marker)
        self._tag_cache.clear()
        self._tag_cache.update(self._list_tags(TagScope.EFFECTIVE))
        if recursive and isinstance(self, TopoMixein):
            for child in self.get_children():
                if isinstance(child, TaggedMixin):
                    child._refresh_tag_cache(recursive=True, _visited=visited)

    def _apply_tag(
        self, tag: str, *, normalize: bool = True, propagate: Optional[bool] = None
    ) -> None:
        if normalize:
            tag = normalize_tag(tag, strict=True)
        if propagate is None:
            propagate = False
        self._add_tag_binding(
            internal_tag_binding(
                tag,
                topology=(
                    TopologyPropagation.DOWNWARD
                    if propagate
                    else TopologyPropagation.LOCAL
                ),
            )
        )

    def _apply_user_tag(
        self,
        tag: str,
        *,
        topology_propagation: str | TopologyPropagation = TopologyPropagation.LOCAL,
        lineage_policy: str | LineagePolicy = LineagePolicy.CONTINUATION_FRAGMENT,
        producer_node_id: Optional[str] = None,
    ) -> TagBinding:
        binding = user_tag_binding(
            normalize_tag(tag, strict=True),
            node_id=producer_node_id,
            topology=topology_propagation,
            lineage=lineage_policy,
        )
        self._add_tag_binding(binding)
        return binding

    def _propagate_tag_down(self, tag: str) -> None:
        # Inheritance is evaluated from ancestor bindings; no strings are copied.
        return

    def _remove_tag(
        self,
        tag: str,
        *,
        matching_producer: TagProducer | TagProducerKind | str = TagProducerKind.USER_OPERATION,
    ) -> int:
        normalized = normalize_tag(tag, strict=True)

        def matches(binding: TagBinding) -> bool:
            if isinstance(matching_producer, TagProducer):
                return binding.producer == matching_producer
            try:
                producer_kind = (
                    matching_producer
                    if isinstance(matching_producer, TagProducerKind)
                    else TagProducerKind(matching_producer)
                )
            except ValueError as exc:
                raise ValueError(
                    f"unsupported matching producer '{matching_producer}'"
                ) from exc
            return binding.producer.kind == producer_kind

        retained = [
            binding
            for binding in self._tag_bindings
            if not (binding.tag == normalized and matches(binding))
        ]
        removed = len(self._tag_bindings) - len(retained)
        self._tag_bindings[:] = retained
        if removed:
            self._refresh_tag_cache(recursive=True)
        return removed

    def _remove_tag_binding(self, binding_id: str) -> bool:
        if not isinstance(binding_id, str) or not binding_id:
            raise ValueError("binding_id must be a non-empty string")
        retained = [
            binding
            for binding in self._tag_bindings
            if binding.binding_id != binding_id
        ]
        removed = len(retained) != len(self._tag_bindings)
        self._tag_bindings[:] = retained
        if removed:
            self._refresh_tag_cache(recursive=True)
        return removed

    def _has_tag(
        self, tag: str, scope: str | TagScope = TagScope.EFFECTIVE
    ) -> bool:
        return tag in self._list_tags(scope)

    def _local_tag_bindings(self) -> List[TagBinding]:
        return [
            binding
            for binding in self._tag_bindings
            if binding.attachment == TagAttachment.LOCAL
        ]

    def _legacy_effective_bindings(self) -> List[TagBinding]:
        return [
            binding
            for binding in self._tag_bindings
            if binding.attachment == TagAttachment.EFFECTIVE_LEGACY
        ]

    def _inherited_tag_bindings_with_paths(
        self,
    ) -> List[Tuple[TagBinding, Tuple[str, ...]]]:
        result: List[Tuple[TagBinding, Tuple[str, ...]]] = []
        seen_bindings: Set[str] = set()
        seen_objects: Set[int] = set()
        wrappers = (
            self._entity.wrappers
            if getattr(self, "_entity", None) is not None
            else [self]
        )
        queue: List[Tuple[Any, Tuple[str, ...]]] = [
            (parent, (self.topo_id, getattr(parent, "topo_id", str(id(parent)))))
            for wrapper in wrappers
            if isinstance(wrapper, TopoMixein)
            for parent in wrapper.get_parents()
        ]
        while queue:
            parent, path = queue.pop(0)
            marker = id(parent)
            if marker in seen_objects:
                continue
            seen_objects.add(marker)
            if isinstance(parent, TaggedMixin):
                for binding in parent._local_tag_bindings():
                    if (
                        binding.propagation.topology == TopologyPropagation.DOWNWARD
                        and binding.binding_id not in seen_bindings
                    ):
                        seen_bindings.add(binding.binding_id)
                        result.append((binding, tuple(reversed(path))))
            if isinstance(parent, TopoMixein):
                for ancestor in parent.get_parents():
                    queue.append(
                        (
                            ancestor,
                            (*path, getattr(ancestor, "topo_id", str(id(ancestor)))),
                        )
                    )
        return result

    def _inherited_tag_bindings(self) -> List[TagBinding]:
        return [binding for binding, _path in self._inherited_tag_bindings_with_paths()]

    def _lineage_tag_bindings(self) -> List[TagBinding]:
        coverage = self._runtime.get("semantic.lineage.coverage")
        if coverage != "complete":
            available = "none" if coverage is None else str(coverage)
            raise UnsupportedQueryCapabilityError(
                "lineage tag scope requires complete topology history; "
                f"coverage={available}"
            )
        if any(witness.coverage != "complete" for witness in self._tag_lineage):
            raise UnsupportedQueryCapabilityError(
                "lineage tag scope has incomplete lineage witnesses"
            )
        result: List[TagBinding] = []
        seen: Set[str] = set()
        for witness in self._tag_lineage:
            binding = witness.binding
            if (
                lineage_policy_allows(binding.propagation, witness.derivation)
                and binding.binding_id not in seen
            ):
                seen.add(binding.binding_id)
                result.append(binding)
        return result

    def _list_tag_bindings(
        self, scope: str | TagScope = TagScope.EFFECTIVE
    ) -> List[TagBinding]:
        resolved_scope = normalize_tag_scope(scope)
        if (
            resolved_scope != TagScope.EFFECTIVE
            and self._legacy_effective_bindings()
        ):
            raise UnsupportedQueryCapabilityError(
                "legacy effective tag snapshots only support effective scope"
            )
        if resolved_scope == TagScope.LOCAL:
            return self._local_tag_bindings()
        if resolved_scope == TagScope.INHERITED:
            return self._inherited_tag_bindings()
        if resolved_scope == TagScope.LINEAGE:
            return self._lineage_tag_bindings()

        bindings = [
            *self._local_tag_bindings(),
            *self._inherited_tag_bindings(),
            *self._legacy_effective_bindings(),
        ]
        unique: Dict[str, TagBinding] = {}
        for binding in bindings:
            unique.setdefault(binding.binding_id, binding)
        return list(unique.values())

    def _list_tags(
        self, scope: str | TagScope = TagScope.EFFECTIVE
    ) -> list[str]:
        return sorted({binding.tag for binding in self._list_tag_bindings(scope)})

    def _explain_tag(
        self, tag: str, scope: str | TagScope = TagScope.EFFECTIVE
    ) -> List[Dict[str, Any]]:
        normalized = normalize_tag(tag, strict=True)
        resolved_scope = normalize_tag_scope(scope)
        inherited_paths = {
            binding.binding_id: path
            for binding, path in self._inherited_tag_bindings_with_paths()
        }
        explanations: List[Dict[str, Any]] = []
        for binding in self._list_tag_bindings(resolved_scope):
            if binding.tag != normalized:
                continue
            attachment = binding.attachment.value
            explanation: Dict[str, Any] = {
                "scope": resolved_scope.value,
                "binding_id": binding.binding_id,
                "producer": binding.producer.to_dict(),
                "attachment": attachment,
                "binding": binding.to_dict(),
            }
            if binding.binding_id in inherited_paths:
                explanation["attachment"] = TagAttachment.INHERITED.value
                explanation["topology_path"] = list(
                    inherited_paths[binding.binding_id]
                )
            witnesses = [
                witness
                for witness in self._tag_lineage
                if witness.binding.binding_id == binding.binding_id
                and lineage_policy_allows(binding.propagation, witness.derivation)
            ]
            if witnesses:
                explanation["lineage"] = [
                    {
                        "derivation": witness.derivation.value,
                        "source_topo_id": witness.source_topo_id,
                        "target_topo_id": witness.target_topo_id,
                        "coverage": witness.coverage,
                        "evidence": witness.evidence.to_dict(),
                    }
                    for witness in witnesses
                ]
            explanations.append(explanation)
        return explanations

    def set_metadata(self, key: str, value: Any) -> None:
        self._metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self._metadata.get(key, default)

    def _set_runtime(self, key: str, value: Any) -> None:
        self._runtime[key] = value

    def _get_runtime(self, key: str, default: Any = None) -> Any:
        return self._runtime.get(key, default)

    def _format_tags_and_metadata(self, indent: int = 0) -> str:
        spaces = "  " * indent
        result = []
        tags = self._list_tags()
        if tags:
            result.append(f"{spaces}tags: [{', '.join(tags)}]")
        if self._metadata:
            result.append(f"{spaces}metadata:")
            for key, value in sorted(self._metadata.items()):
                result.append(f"{spaces}  {key}: {value}")
        return "\n".join(result)


class TopoMixein:
    """Topology management mixin."""

    def __init__(self, level: int, self_shape_ref: "AnyShape") -> None:
        self.level: int = level
        self.self_shape_ref: AnyShape = self_shape_ref
        self.children: List[AnyShape] = []
        self.parent: Optional[AnyShape] = None
        self.parents: List[AnyShape] = []

    def __reduce__(self) -> Tuple[Any, Tuple[Any, ...]]:
        # Kernel handles cannot be pickled: store exact BinTools bytes plus
        # per-entity semantic state (see _internal/shape_pickle.py).
        from ._internal.shape_pickle import reduce_shape

        return reduce_shape(cast("AnyShape", self))

    def set_parent(self, parent: "AnyShape") -> None:
        self.parent = parent
        if parent not in self.parents:
            self.parents.append(parent)

    def add_parent(self, parent: "AnyShape") -> None:
        self.set_parent(parent)

    def add_child(self, child: "AnyShape") -> None:
        if child not in self.children:
            self.children.append(child)
            child.set_parent(self.self_shape_ref)
            if isinstance(child, TaggedMixin):
                child._refresh_tag_cache(recursive=True)

    def get_children(self) -> List["AnyShape"]:
        return self.children

    def get_parent(self) -> Optional["AnyShape"]:
        return self.parent

    def get_parents(self) -> List["AnyShape"]:
        return list(self.parents)


def _record_indexed_topology_selection(source: Any, selected_shapes: Iterable[Any]) -> None:
    shapes = [shape for shape in selected_shapes if isinstance(shape, TaggedMixin)]
    if not shapes:
        return
    try:
        from .operators._support import _ensure_geo_selection_node_ids

        _ensure_geo_selection_node_ids(cast(AnyShape, source), cast(List[AnyShape], shapes))
    except Exception:
        return


def _topology_enumeration_error(method: str, kind: str) -> SimpleCADError:
    """Bare topology enumeration is forbidden: reads go through QL selectors."""
    from .errors import ErrorGuidance

    return SimpleCADError(
        f"{method} (no index)",
        ErrorGuidance(
            what_happened=(
                f"{method}() without an index no longer returns a list — "
                "bare topology enumeration is not part of the public API."
            ),
            possible_causes=(
                "Calling a plural topology getter (get_edges/get_faces/...) with no argument.",
                "Porting code that enumerated topology with Python loops or len().",
            ),
            how_to_fix=(
                "Enumerate or measure via QL: ql.edges().resolve(shape) / len(ql.faces().resolve(shape)).",
                "Pick intentionally with the indexed form get_edges(index) — indexed picks "
                "are recorded as graph selection nodes.",
                "Filter with QL predicates and cardinality (take/exactly) instead of "
                "post-filtering an enumerated list.",
            ),
            signature=f"{method}(index: int) -> {kind.capitalize()}",
            technical_details=(
                "Enumeration escapes the graph: selections made by indexing a bare list "
                "carry no predicate and capture kernel artifacts (e.g. periodic-face seams)."
            ),
        ),
    )


def _indexed_topology_pick(
    source: Any,
    kind: str,
    items: List[Any],
    index: Optional[int],
    method: str,
) -> Any:
    if index is None:
        raise _topology_enumeration_error(method, kind)
    selected = items[index]
    _record_indexed_topology_selection(source, [selected])
    return selected


class Vertex(TaggedMixin, TopoMixein):
    """OCP-native vertex wrapper with tag support."""

    def __init__(self, vertex: Any, cache: Optional[_TopologyEntityCache] = None):
        try:
            self.wrapped = as_vertex(vertex)
            self._topology_cache = cache or _TopologyEntityCache()
            TaggedMixin.__init__(self, self._topology_cache.get("vertex", self.wrapped))
            TopoMixein.__init__(self, level=0, self_shape_ref=self)
        except Exception as e:
            raise ValueError(f"初始化顶点失败: {e}. 请检查输入的顶点对象是否有效。")

    def get_coordinates(self) -> Tuple[float, float, float]:
        try:
            return vertex_point(self.wrapped)
        except Exception as e:
            raise ValueError(f"获取顶点坐标失败: {e}")

    def get_incident_edges(self) -> List["Edge"]:
        edges: List[Edge] = []
        for edge_id in getattr(self._entity, "incident_edge_ids", set()):
            for wrapper in self._topology_cache.wrappers_for(edge_id):
                if isinstance(wrapper, Edge) and wrapper.topo_id == edge_id:
                    edges.append(wrapper)
                    break
        return edges

    def __str__(self) -> str:
        return self._format_string(indent=0)

    def __repr__(self) -> str:
        return f"Vertex(coordinates={self.get_coordinates()})"

    def _format_string(self, indent: int = 0, show_coordinate_system: bool = False) -> str:
        spaces = "  " * indent
        coords = self.get_coordinates()
        result = [f"{spaces}Vertex:", f"{spaces}  coordinates: [{coords[0]:.3f}, {coords[1]:.3f}, {coords[2]:.3f}]"]
        tags_metadata = self._format_tags_and_metadata(indent + 1)
        if tags_metadata:
            result.append(tags_metadata)
        return "\n".join(result)


class Edge(TaggedMixin, TopoMixein):
    """OCP-native edge wrapper with tag support."""

    def __init__(self, edge: Any, cache: Optional[_TopologyEntityCache] = None):
        try:
            self.wrapped = as_edge(edge)
            self._topology_cache = cache or _TopologyEntityCache()
            TaggedMixin.__init__(self, self._topology_cache.get("edge", self.wrapped))
            TopoMixein.__init__(self, level=1, self_shape_ref=self)
            for vertex in vertices_of(self.wrapped):
                child_vertex = Vertex(vertex, cache=self._topology_cache)
                self.add_child(child_vertex)
                child_vertex._entity.incident_edge_ids.add(self.topo_id)
        except Exception as e:
            raise ValueError(f"初始化边失败: {e}. 请检查输入的边对象是否有效。")

    def get_length(self) -> float:
        try:
            return float(linear_length(self.wrapped))
        except Exception as e:
            raise ValueError(f"获取边长度失败: {e}")

    def get_start_vertex(self) -> Vertex:
        try:
            if len(self.get_children()) < 1:
                raise ValueError("边没有顶点")
            return cast(Vertex, self.get_children()[0])
        except Exception as e:
            raise ValueError(f"获取起始顶点失败: {e}")

    def get_end_vertex(self) -> Vertex:
        try:
            if len(self.get_children()) < 2:
                raise ValueError("边没有足够的顶点")
            return cast(Vertex, self.get_children()[-1])
        except Exception as e:
            raise ValueError(f"获取结束顶点失败: {e}")

    def get_center(self) -> Vec3:
        return center_of_mass(self.wrapped)

    def get_incident_faces(self) -> List["Face"]:
        faces: List[Face] = []
        for face_id in getattr(self._entity, "incident_face_ids", set()):
            for wrapper in self._topology_cache.wrappers_for(face_id):
                if isinstance(wrapper, Face) and wrapper.topo_id == face_id:
                    faces.append(wrapper)
                    break
        return faces

    def _iter_vertices(self) -> List[Vertex]:
        return [child for child in self.get_children() if isinstance(child, Vertex)]

    def get_vertices(self, index: Optional[int] = None) -> Vertex:
        try:
            return cast(
                Vertex,
                _indexed_topology_pick(self, "vertex", self._iter_vertices(), index, "get_vertices"),
            )
        except SimpleCADError:
            raise
        except Exception as e:
            raise ValueError(f"获取顶点失败: {e}")

    def __str__(self) -> str:
        return self._format_string(indent=0)

    def __repr__(self) -> str:
        length = self.get_length()
        try:
            part1 = f"from: {self.get_start_vertex().get_coordinates()}, to: {self.get_end_vertex().get_coordinates()}"
        except Exception:
            part1 = "from: [unable to retrieve], to: [unable to retrieve], usually this is a closed edge"
        return f"Edge({part1}, length={length:.3f}, tags={self._list_tags()})"

    def _format_string(self, indent: int = 0, show_coordinate_system: bool = False) -> str:
        spaces = "  " * indent
        result = [f"{spaces}Edge:", f"{spaces}  length: {self.get_length():.3f}"]
        try:
            result.append(f"{spaces}  vertices:")
            result.append(f"{spaces}    start: {self.get_start_vertex().get_coordinates()}")
            result.append(f"{spaces}    end: {self.get_end_vertex().get_coordinates()}")
        except Exception:
            result.append(f"{spaces}  vertices: [unable to retrieve, usually a closed edge]")
        tags_metadata = self._format_tags_and_metadata(indent + 1)
        if tags_metadata:
            result.append(tags_metadata)
        return "\n".join(result)


class Wire(TaggedMixin, TopoMixein):
    """OCP-native wire wrapper with tag support."""

    def __init__(self, wire: Any, cache: Optional[_TopologyEntityCache] = None):
        try:
            self.wrapped = as_wire(wire)
            self._topology_cache = cache or _TopologyEntityCache()
            TaggedMixin.__init__(self, self._topology_cache.get("wire", self.wrapped))
            TopoMixein.__init__(self, level=2, self_shape_ref=self)
            for edge in edges_of(self.wrapped):
                self.add_child(Edge(edge, cache=self._topology_cache))
            self._tag_edges()
        except Exception as e:
            raise ValueError(f"初始化线失败: {e}. 请检查输入的线对象是否有效。")

    def _iter_edges(self) -> List[Edge]:
        return cast(List[Edge], self.get_children())

    def get_edges(self, index: Optional[int] = None) -> Edge:
        try:
            return cast(
                Edge,
                _indexed_topology_pick(self, "edge", self._iter_edges(), index, "get_edges"),
            )
        except SimpleCADError:
            raise
        except Exception as e:
            raise ValueError(f"获取边失败: {e}")

    def is_closed(self) -> bool:
        try:
            return bool(is_wire_closed(self.wrapped))
        except Exception as e:
            raise ValueError(f"检查线闭合性失败: {e}")

    def _tag_edges(self) -> None:
        for i, edge in enumerate(self._iter_edges()):
            edge._apply_tag("edge.boundary", propagate=False)
            geo = dict(edge.get_metadata("geo", {}))
            geo["edge_index"] = i
            edge.set_metadata("geo", geo)

    def __str__(self) -> str:
        return self._format_string(indent=0)

    def __repr__(self) -> str:
        return f"Wire(edge_count={len(self._iter_edges())}, closed={self.is_closed()}, tags={self._list_tags()})"

    def _format_string(self, indent: int = 0, show_coordinate_system: bool = False) -> str:
        spaces = "  " * indent
        edges = self._iter_edges()
        result = [f"{spaces}Wire:", f"{spaces}  edge_count: {len(edges)}", f"{spaces}  closed: {self.is_closed()}"]
        if edges:
            result.append(f"{spaces}  edges:")
            for i, edge in enumerate(edges):
                result.append(f"{spaces}    edge_{i}:")
                result.append(edge._format_string(indent + 3, False))
        tags_metadata = self._format_tags_and_metadata(indent + 1)
        if tags_metadata:
            result.append(tags_metadata)
        return "\n".join(result)


class Face(TaggedMixin, TopoMixein):
    """OCP-native face wrapper with tag support."""

    def __init__(self, face: Any, cache: Optional[_TopologyEntityCache] = None):
        try:
            self.wrapped = as_face(face)
            self._topology_cache = cache or _TopologyEntityCache()
            TaggedMixin.__init__(self, self._topology_cache.get("face", self.wrapped))
            TopoMixein.__init__(self, level=3, self_shape_ref=self)
            outer_wire = Wire(outer_wire_of(self.wrapped), cache=self._topology_cache)
            outer_wire._apply_tag("wire.outer", propagate=False)
            self.add_child(outer_wire)
            outer_wire._entity.incident_face_ids.add(self.topo_id)
            for edge in outer_wire._iter_edges():
                edge._entity.incident_face_ids.add(self.topo_id)
            for wire in inner_wires_of(self.wrapped):
                inner = Wire(wire, cache=self._topology_cache)
                inner._apply_tag("wire.inner", propagate=False)
                self.add_child(inner)
                inner._entity.incident_face_ids.add(self.topo_id)
                for edge in inner._iter_edges():
                    edge._entity.incident_face_ids.add(self.topo_id)
        except Exception as e:
            raise ValueError(f"初始化面失败: {e}. 请检查输入的面对象是否有效。")

    def get_area(self) -> float:
        try:
            return float(surface_area(self.wrapped))
        except Exception as e:
            raise ValueError(f"获取面积失败: {e}")

    def get_normal_at(self, u: float = 0.5, v: float = 0.5) -> Vec3:
        try:
            return face_normal_at(self.wrapped, u, v)
        except Exception as e:
            raise ValueError(f"获取法向量失败: {e}")

    def _tag_wires(self) -> None:
        outer_wire = self.get_outer_wire()
        outer_wire._apply_tag("wire.outer", propagate=False)
        outer_wire._tag_edges()
        for i, inner in enumerate(self._iter_inner_wires()):
            inner._apply_tag("wire.inner", propagate=False)
            geo = dict(inner.get_metadata("geo", {}))
            geo["inner_wire_index"] = i
            inner.set_metadata("geo", geo)
            inner._tag_edges()

    def get_outer_wire(self) -> Wire:
        try:
            return [w for w in cast(List[Wire], self.get_children()) if w.is_closed() and w._has_tag("wire.outer")][0]
        except Exception as e:
            raise ValueError(f"获取外边界线失败: {e}")

    def _iter_wires(self) -> List[Wire]:
        return [child for child in self.get_children() if isinstance(child, Wire)]

    def get_wires(self, index: Optional[int] = None) -> Wire:
        try:
            return cast(
                Wire,
                _indexed_topology_pick(self, "wire", self._iter_wires(), index, "get_wires"),
            )
        except SimpleCADError:
            raise
        except Exception as e:
            raise ValueError(f"获取边界线失败: {e}")

    def _iter_inner_wires(self) -> List[Wire]:
        return [
            w
            for w in cast(List[Wire], self.get_children())
            if w.is_closed() and w._has_tag("wire.inner")
        ]

    def get_inner_wires(self, index: Optional[int] = None) -> Wire:
        try:
            return cast(
                Wire,
                _indexed_topology_pick(
                    self, "wire", self._iter_inner_wires(), index, "get_inner_wires"
                ),
            )
        except SimpleCADError:
            raise
        except Exception as e:
            raise ValueError(f"获取内边界线失败: {e}")

    def get_center(self) -> Vec3:
        return center_of_mass(self.wrapped)

    def _iter_edges(self) -> List[Edge]:
        edges: List[Edge] = []
        edges.extend(self.get_outer_wire()._iter_edges())
        for inner in self._iter_inner_wires():
            edges.extend(inner._iter_edges())
        return edges

    def get_edges(self, index: Optional[int] = None) -> Edge:
        try:
            return cast(
                Edge,
                _indexed_topology_pick(self, "edge", self._iter_edges(), index, "get_edges"),
            )
        except SimpleCADError:
            raise
        except Exception as e:
            raise ValueError(f"获取边失败: {e}")

    def get_adjacent_faces(self) -> List["Face"]:
        adjacent: Dict[str, Face] = {}
        for edge in self._iter_edges():
            for face in edge.get_incident_faces():
                if face.topo_id != self.topo_id:
                    adjacent.setdefault(face.topo_id, face)
        return list(adjacent.values())

    def __str__(self) -> str:
        return self._format_string(indent=0)

    def __repr__(self) -> str:
        return f"Face(area={self.get_area():.3f}, normal={self.get_normal_at()}, center={self.get_center()}, tags={self._list_tags()})"

    def _format_string(self, indent: int = 0, show_coordinate_system: bool = False) -> str:
        spaces = "  " * indent
        result = [f"{spaces}Face:", f"{spaces}  area: {self.get_area():.3f}, center: {self.get_center()}"]
        try:
            normal = self.get_normal_at()
            result.append(f"{spaces}  normal: [{normal.x:.3f}, {normal.y:.3f}, {normal.z:.3f}]")
        except Exception:
            result.append(f"{spaces}  normal: [unable to retrieve]")
        try:
            result.append(f"{spaces}  outer_wire:")
            result.append(self.get_outer_wire()._format_string(indent + 2, False))
        except Exception:
            result.append(f"{spaces}  outer_wire: [unable to retrieve]")
        try:
            for inner in self._iter_inner_wires():
                result.append(f"{spaces}  inner_wire:")
                result.append(inner._format_string(indent + 2, False))
        except Exception:
            result.append(f"{spaces}  inner_wires: [unable to retrieve]")
        tags_metadata = self._format_tags_and_metadata(indent + 1)
        if tags_metadata:
            result.append(tags_metadata)
        return "\n".join(result)


class Shell(TaggedMixin, TopoMixein):
    """OCP-native connected surface shell with face and edge topology."""

    def __init__(self, shell: Any, cache: Optional[_TopologyEntityCache] = None):
        try:
            self.wrapped = as_shell(shell)
            self._topology_cache = cache or _TopologyEntityCache()
            TaggedMixin.__init__(
                self, self._topology_cache.get("shell", self.wrapped)
            )
            TopoMixein.__init__(self, level=4, self_shape_ref=self)
            for face in faces_of(self.wrapped):
                self.add_child(Face(face, cache=self._topology_cache))
            for wire in free_boundaries(self.wrapped, tolerance=1e-7):
                self.add_child(Wire(wire, cache=self._topology_cache))
        except Exception as e:
            raise ValueError(
                f"Failed to initialize Shell: {e}. Expected one connected OCP shell."
            ) from e

    def get_area(self) -> float:
        """Return the total area of every face in the shell."""

        return float(surface_area(self.wrapped))

    def is_closed(self) -> bool:
        """Return whether the shell bounds a closed region."""

        return shell_is_closed(self.wrapped)

    def _iter_faces(self) -> List[Face]:
        return [
            face for face in cast(List[Face], self.get_children()) if isinstance(face, Face)
        ]

    def get_faces(self, index: Optional[int] = None) -> Face:
        return cast(
            Face,
            _indexed_topology_pick(self, "face", self._iter_faces(), index, "get_faces"),
        )

    def _iter_wires(self) -> List[Wire]:
        """The Shell's free boundary wires."""

        return [
            wire
            for wire in cast(List[Wire], self.get_children())
            if isinstance(wire, Wire)
        ]

    def get_wires(self, index: Optional[int] = None) -> Wire:
        return cast(
            Wire,
            _indexed_topology_pick(self, "wire", self._iter_wires(), index, "get_wires"),
        )

    def _iter_edges(self) -> List[Edge]:
        unique: Dict[str, Edge] = {}
        for face in self._iter_faces():
            for edge in face._iter_edges():
                unique.setdefault(edge.topo_id, edge)
        return list(unique.values())

    def get_edges(self, index: Optional[int] = None) -> Edge:
        return cast(
            Edge,
            _indexed_topology_pick(self, "edge", self._iter_edges(), index, "get_edges"),
        )

    def __repr__(self) -> str:
        return (
            f"Shell(faces={len(self._iter_faces())}, area={self.get_area():.3f}, "
            f"closed={self.is_closed()}, tags={self._list_tags()})"
        )


class Solid(TaggedMixin, TopoMixein):
    """OCP-native solid wrapper with tag support."""

    def __init__(self, solid: Any, cache: Optional[_TopologyEntityCache] = None):
        try:
            self.wrapped = as_solid(solid)
            self._topology_cache = cache or _TopologyEntityCache()
            TaggedMixin.__init__(self, self._topology_cache.get("solid", self.wrapped))
            TopoMixein.__init__(self, level=4, self_shape_ref=self)
            for face in faces_of(self.wrapped):
                self.add_child(Face(face, cache=self._topology_cache))
            try:
                from ._internal.mesh import attach_default_mesh

                attach_default_mesh(self)
            except Exception as mesh_error:
                self._set_runtime("mesh.error", str(mesh_error))
        except Exception as e:
            raise ValueError(f"初始化实体失败: {e}. 请检查输入的实体对象是否有效。")

    def get_volume(self) -> float:
        try:
            return float(volume(self.wrapped))
        except Exception as e:
            raise ValueError(f"获取体积失败: {e}")

    def _iter_faces(self) -> List[Face]:
        return [
            f for f in cast(List[Face], self.get_children()) if isinstance(f, Face)
        ]

    def get_faces(self, index: Optional[int] = None) -> Face:
        try:
            return cast(
                Face,
                _indexed_topology_pick(self, "face", self._iter_faces(), index, "get_faces"),
            )
        except SimpleCADError:
            raise
        except Exception as e:
            raise ValueError(f"获取面失败: {e}")

    def _iter_edges(self) -> List[Edge]:
        unique: Dict[str, Edge] = {}
        for face in self._iter_faces():
            for edge in face._iter_edges():
                unique.setdefault(edge.topo_id, edge)
        return list(unique.values())

    def get_edges(self, index: Optional[int] = None) -> Edge:
        try:
            return cast(
                Edge,
                _indexed_topology_pick(self, "edge", self._iter_edges(), index, "get_edges"),
            )
        except SimpleCADError:
            raise
        except Exception as e:
            raise ValueError(f"获取边失败: {e}")

    def _iter_edge_occurrences(self) -> List[Edge]:
        edges: List[Edge] = []
        for face in self._iter_faces():
            edges.extend(face._iter_edges())
        return edges

    def get_edge_occurrences(self, index: Optional[int] = None) -> Edge:
        try:
            return cast(
                Edge,
                _indexed_topology_pick(
                    self, "edge", self._iter_edge_occurrences(), index, "get_edge_occurrences"
                ),
            )
        except SimpleCADError:
            raise
        except Exception as e:
            raise ValueError(f"获取边实例列表失败: {e}")

    def auto_tag_faces(self, geometry_type: str = "unknown") -> None:
        try:
            faces = self._iter_faces()
            if geometry_type == "box" and len(faces) == 6:
                self._auto_tag_box_faces(faces)
            elif geometry_type == "cylinder" and len(faces) == 3:
                self._auto_tag_cylinder_faces(faces)
            elif geometry_type == "sphere" and len(faces) == 1:
                self._tag_face(next(iter(faces)), "surface")
            else:
                for i, face in enumerate(faces):
                    self._tag_face(face, f"face_{i}")
        except Exception as e:
            raise ValueError(f"自动标记面失败: {e}")

    def _auto_tag_box_faces(self, faces: List[Face]) -> None:
        try:
            for i, face in enumerate(faces):
                normal = face.get_normal_at()
                if abs(normal.z) > 0.9:
                    tag = "top" if normal.z > 0 else "bottom"
                elif abs(normal.y) > 0.9:
                    tag = "front" if normal.y > 0 else "back"
                elif abs(normal.x) > 0.9:
                    tag = "right" if normal.x > 0 else "left"
                else:
                    tag = f"face_{i}"
                self._tag_face(face, tag)
        except Exception as e:
            print(f"警告: 自动标记立方体面失败: {e}")

    def _auto_tag_cylinder_faces(self, faces: List[Face]) -> None:
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.GeomAbs import GeomAbs_Plane

            plane_faces = []
            side_faces = []
            for face in faces:
                surface_type = BRepAdaptor_Surface(face.wrapped).GetType()
                if surface_type == GeomAbs_Plane:
                    plane_faces.append(face)
                else:
                    side_faces.append(face)
            if len(plane_faces) != 2:
                raise ValueError(f"预期找到2个平面面，但找到了 {len(plane_faces)} 个")
            centers = [face.get_center() for face in plane_faces]
            spans = [
                abs(centers[1].x - centers[0].x),
                abs(centers[1].y - centers[0].y),
                abs(centers[1].z - centers[0].z),
            ]
            axis_index = max(range(3), key=lambda index: spans[index])
            plane_faces.sort(
                key=lambda face: (
                    face.get_center().x,
                    face.get_center().y,
                    face.get_center().z,
                )[axis_index]
            )
            bottom_face, top_face = plane_faces
            self._tag_face(bottom_face, "bottom")
            self._tag_face(top_face, "top")
            for face in side_faces:
                self._tag_face(face, "side")
        except Exception as e:
            print(f"警告: 自动标记圆柱体面失败: {e}")

    def _tag_face(self, face: Face, tag: str) -> None:
        face._apply_tag(f"face.{tag}", propagate=False)
        face._tag_wires()

    def __str__(self) -> str:
        return self._format_string(indent=0)

    def __repr__(self) -> str:
        return f"Solid(volume={self.get_volume():.3f}, faces={len(self._iter_faces())}, tags={self._list_tags()})"

    def _format_string(self, indent: int = 0, show_coordinate_system: bool = True) -> str:
        spaces = "  " * indent
        faces = self._iter_faces()
        edges = self._iter_edges()
        result = [f"{spaces}Solid:", f"{spaces}  volume: {self.get_volume():.3f}", f"{spaces}  face_count: {len(faces)}", f"{spaces}  edge_count: {len(edges)}"]
        if show_coordinate_system:
            current_cs = get_current_cs()
            if current_cs != WORLD_CS:
                result.append(f"{spaces}  coordinate_system:")
                result.append(current_cs._format_string(indent + 2))
        if faces:
            result.append(f"{spaces}  faces:")
            for i, face in enumerate(faces):
                result.append(f"{spaces}    face_{i}:")
                result.append(face._format_string(indent + 3, False))
        tags_metadata = self._format_tags_and_metadata(indent + 1)
        if tags_metadata:
            result.append(tags_metadata)
        return "\n".join(result)


class Compound(TaggedMixin, TopoMixein):
    """OCP-native compound wrapper for explicit multi-shape projections."""

    def __init__(self, compound: Any, cache: Optional[_TopologyEntityCache] = None):
        try:
            self.wrapped = as_compound(compound)
            self._topology_cache = cache or _TopologyEntityCache()
            TaggedMixin.__init__(self, self._topology_cache.get("compound", self.wrapped))
            TopoMixein.__init__(self, level=5, self_shape_ref=self)
            for solid in solids_of(self.wrapped):
                self.add_child(Solid(solid, cache=self._topology_cache))
        except Exception as e:
            raise ValueError(f"初始化组合体失败: {e}. 请检查输入的组合体对象是否有效。")

    def _iter_solids(self) -> List[Solid]:
        return [
            child for child in self.get_children() if isinstance(child, Solid)
        ]

    def get_solids(self, index: Optional[int] = None) -> Solid:
        try:
            return cast(
                Solid,
                _indexed_topology_pick(self, "solid", self._iter_solids(), index, "get_solids"),
            )
        except SimpleCADError:
            raise
        except Exception as e:
            raise ValueError(f"获取实体列表失败: {e}")

    def _iter_faces(self) -> List[Face]:
        faces: List[Face] = []
        for solid in self._iter_solids():
            faces.extend(solid._iter_faces())
        return faces

    def get_faces(self, index: Optional[int] = None) -> Face:
        try:
            return cast(
                Face,
                _indexed_topology_pick(self, "face", self._iter_faces(), index, "get_faces"),
            )
        except SimpleCADError:
            raise
        except Exception as e:
            raise ValueError(f"获取面失败: {e}")

    def _iter_edges(self) -> List[Edge]:
        unique: Dict[str, Edge] = {}
        for face in self._iter_faces():
            for edge in face._iter_edges():
                unique.setdefault(edge.topo_id, edge)
        return list(unique.values())

    def get_edges(self, index: Optional[int] = None) -> Edge:
        try:
            return cast(
                Edge,
                _indexed_topology_pick(self, "edge", self._iter_edges(), index, "get_edges"),
            )
        except SimpleCADError:
            raise
        except Exception as e:
            raise ValueError(f"获取边失败: {e}")

    def get_volume(self) -> float:
        return sum(float(solid.get_volume()) for solid in self._iter_solids())

    def __str__(self) -> str:
        return self._format_string(indent=0)

    def __repr__(self) -> str:
        return f"Compound(solids={len(self._iter_solids())}, volume={self.get_volume():.3f}, tags={self._list_tags()})"

    def _format_string(self, indent: int = 0, show_coordinate_system: bool = True) -> str:
        spaces = "  " * indent
        solids = self._iter_solids()
        result = [
            f"{spaces}Compound:",
            f"{spaces}  solid_count: {len(solids)}",
            f"{spaces}  volume: {self.get_volume():.3f}",
        ]
        tags_metadata = self._format_tags_and_metadata(indent + 1)
        if tags_metadata:
            result.append(tags_metadata)
        return "\n".join(result)


AnyShape = Union[Vertex, Edge, Wire, Face, Shell, Solid, Compound]


def _same_semantic_topology(kind: str, left: Any, right: Any) -> bool:
    try:
        if left.IsSame(right):
            return True
    except Exception:
        return False
    if kind != "wire":
        return False
    left_edges = edges_of(left)
    right_edges = edges_of(right)
    if len(left_edges) != len(right_edges):
        return False
    return all(
        any(left_edge.IsSame(right_edge) for right_edge in right_edges)
        for left_edge in left_edges
    )


def clone_semantic_shape_view(shape: AnyShape) -> AnyShape:
    """Create an independent semantic view over the same kernel geometry."""

    if not isinstance(shape, (Vertex, Edge, Wire, Face, Shell, Solid, Compound)):
        raise TypeError("shape must be a SimpleCAD topology object")

    clone = type(shape)(shape.wrapped)
    source_entities = shape._topology_cache.entities()
    matched_source_ids: Set[str] = set()
    for target_entity in clone._topology_cache.entities():
        matches = []
        for source_entity in source_entities:
            if source_entity.kind != target_entity.kind:
                continue
            try:
                if _same_semantic_topology(
                    source_entity.kind,
                    source_entity.representative,
                    target_entity.representative,
                ):
                    matches.append(source_entity)
            except Exception:
                continue
        if len(matches) != 1:
            raise ValueError(
                "semantic shape view topology does not map uniquely to its source"
            )
        source_entity = matches[0]
        if source_entity.topo_id in matched_source_ids:
            raise ValueError("semantic shape view contains a duplicate topology entity")
        matched_source_ids.add(source_entity.topo_id)
        target_entity.topo_id = source_entity.topo_id
        _copy_entity_state(source_entity, target_entity)

    clone._topology_cache._entities_by_id = {
        entity.topo_id: entity for entity in clone._topology_cache.entities()
    }

    clone._refresh_tag_cache(recursive=True)
    return clone
