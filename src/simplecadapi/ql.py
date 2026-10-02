from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    NoReturn,
    Optional,
    Sequence,
    Tuple,
    cast,
    overload,
)

from .errors import (
    ErrorEvidence,
    ErrorMeasurement,
    InventoryEntry,
    SimpleCADError,
    raise_harness_error,
)
from .topology.tagging import (
    SemanticCapabilityError,
    TagScope,
    UnsupportedQueryCapabilityError,
    normalize_tag_scope,
)


Predicate = Callable[[Any], bool]
KeyFn = Callable[[Any], Any]
MISSING = object()
_PROPERTY_RESOLVERS: Dict[str, Callable[[Any, str], Any]] = {}


def _get_tags(
    obj: Any, scope: str | TagScope = TagScope.EFFECTIVE
) -> List[str]:
    resolved_scope = normalize_tag_scope(scope)
    if hasattr(obj, "_list_tags"):
        return list(obj._list_tags(resolved_scope))
    tags = getattr(obj, "_tags", None)
    if tags is None:
        return []
    if resolved_scope != TagScope.EFFECTIVE:
        raise UnsupportedQueryCapabilityError(
            f"{resolved_scope.value} tag scope is unavailable for legacy flat-tag objects"
        )
    return list(tags)


def _track_values(track: dict, plural: str, singular: str) -> List[str]:
    values = track.get(plural)
    if isinstance(values, (list, tuple, set, frozenset)):
        return [str(value) for value in values]
    value = track.get(singular)
    return [str(value)] if value is not None else []


def _operation_names(value: Any) -> set[str]:
    token = str(value).strip()
    token = token[len("op.") :] if token.startswith("op.") else token
    names = {token}
    alias = token[5:] if token.startswith("make_") else token
    for suffix in ("_rsolid", "_rshape", "_rface", "_rwire", "_redge"):
        if alias.endswith(suffix):
            alias = alias[: -len(suffix)]
            break
    names.add(alias)
    return names


def _get_metadata_root(obj: Any) -> dict:
    root = getattr(obj, "_metadata", None)
    if isinstance(root, dict):
        return root
    return {}


def _lookup_metadata(obj: Any, path: str) -> Any:
    if not isinstance(path, str) or not path:
        return None
    segments = path.split(".")
    current: Any = _get_metadata_root(obj)
    for seg in segments:
        if isinstance(current, dict) and seg in current:
            current = current[seg]
        else:
            return None
    return current


def register_property_resolver(
    prefix: str, resolver: Callable[[Any, str], Any]
) -> None:
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("prefix must be a non-empty string")
    _PROPERTY_RESOLVERS[prefix] = resolver


def unregister_property_resolver(prefix: str) -> None:
    _PROPERTY_RESOLVERS.pop(prefix, None)


def _lookup_property(obj: Any, path: str) -> Any:
    if not isinstance(path, str) or not path:
        return MISSING

    if path.startswith("meta."):
        actual = _lookup_metadata(obj, path.split(".", 1)[1])
        return actual if actual is not None else MISSING

    metadata_value = _lookup_metadata(obj, path)
    if metadata_value is not None:
        return metadata_value

    for prefix, resolver in sorted(
        _PROPERTY_RESOLVERS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if path.startswith(prefix):
            value = resolver(obj, path)
            if value is not MISSING:
                return value

    if path == "topo.kind":
        cls_name = obj.__class__.__name__.lower()
        if cls_name in {"vertex", "edge", "wire", "face", "solid", "compound"}:
            return cls_name
        return MISSING

    if path == "topo.loop_role":
        if hasattr(obj, "_has_tag"):
            try:
                if obj._has_tag("wire.outer"):
                    return "outer"
                if obj._has_tag("wire.inner"):
                    return "inner"
            except SemanticCapabilityError:
                raise
            except Exception:
                return MISSING
        return MISSING

    if path == "geom.type":
        gtype = _geom_type(obj)
        return gtype if gtype is not None else MISSING

    if path == "geom.family":
        cls_name = obj.__class__.__name__.lower()
        if cls_name == "edge":
            return "curve"
        if cls_name == "face":
            return "surface"
        if cls_name == "solid":
            return "body"
        if cls_name == "compound":
            return "compound"
        if cls_name == "wire":
            return "wire"
        if cls_name == "vertex":
            return "point"
        return MISSING

    if path.startswith("geom.center."):
        center = _center_tuple(obj)
        if center is None:
            return MISSING
        axis = path.rsplit(".", 1)[1]
        if axis == "x":
            return center[0]
        if axis == "y":
            return center[1]
        if axis == "z":
            return center[2]
        return MISSING

    if path.startswith("geom.normal.") and hasattr(obj, "get_normal_at"):
        try:
            normal = obj.get_normal_at()
            axis = path.rsplit(".", 1)[1]
            if axis == "x":
                return float(normal.x)
            if axis == "y":
                return float(normal.y)
            if axis == "z":
                return float(normal.z)
        except Exception:
            return MISSING

    if path == "geom.length" and hasattr(obj, "get_length"):
        try:
            return float(obj.get_length())
        except Exception:
            return MISSING
    if path == "geom.area" and hasattr(obj, "get_area"):
        try:
            return float(obj.get_area())
        except Exception:
            return MISSING
    if path == "geom.volume" and hasattr(obj, "get_volume"):
        try:
            return float(obj.get_volume())
        except Exception:
            return MISSING
    if path == "geom.closed" and hasattr(obj, "is_closed"):
        try:
            return bool(obj.is_closed())
        except Exception:
            return MISSING

    return MISSING


def _center_tuple(obj: Any) -> Optional[Tuple[float, float, float]]:
    if hasattr(obj, "get_center"):
        try:
            center = obj.get_center()
            if hasattr(center, "x") and hasattr(center, "y") and hasattr(center, "z"):
                return (float(center.x), float(center.y), float(center.z))
        except Exception:
            pass

    if hasattr(obj, "get_start_vertex") and hasattr(obj, "get_end_vertex"):
        try:
            start = obj.get_start_vertex().get_coordinates()
            end = obj.get_end_vertex().get_coordinates()
            return (
                float(start[0] + end[0]) / 2.0,
                float(start[1] + end[1]) / 2.0,
                float(start[2] + end[2]) / 2.0,
            )
        except Exception:
            pass

    if hasattr(obj, "get_coordinates"):
        try:
            coords = obj.get_coordinates()
            return (float(coords[0]), float(coords[1]), float(coords[2]))
        except Exception:
            pass

    return None


def _geom_type(obj: Any) -> Optional[str]:
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
        from OCP.GeomAbs import (
            GeomAbs_BSplineCurve,
            GeomAbs_BSplineSurface,
            GeomAbs_BezierCurve,
            GeomAbs_BezierSurface,
            GeomAbs_Circle,
            GeomAbs_Cone,
            GeomAbs_Cylinder,
            GeomAbs_Line,
            GeomAbs_Plane,
            GeomAbs_Sphere,
            GeomAbs_Torus,
        )
        from .core import Edge, Face

        if isinstance(obj, Edge):
            curve_type = BRepAdaptor_Curve(obj.wrapped).GetType()
            mapping = {
                GeomAbs_Line: "LINE",
                GeomAbs_Circle: "CIRCLE",
                GeomAbs_BSplineCurve: "BSPLINE",
                GeomAbs_BezierCurve: "BEZIER",
            }
            return mapping.get(curve_type, str(curve_type).replace("GeomAbs_CurveType.GeomAbs_", "").upper())
        if isinstance(obj, Face):
            surface_type = BRepAdaptor_Surface(obj.wrapped).GetType()
            mapping = {
                GeomAbs_Plane: "PLANE",
                GeomAbs_Cylinder: "CYLINDER",
                GeomAbs_Cone: "CONE",
                GeomAbs_Sphere: "SPHERE",
                GeomAbs_Torus: "TORUS",
                GeomAbs_BSplineSurface: "BSPLINE",
                GeomAbs_BezierSurface: "BEZIER",
            }
            return mapping.get(surface_type, str(surface_type).replace("GeomAbs_SurfaceType.GeomAbs_", "").upper())
    except Exception:
        return None
    return None


def _compare(actual: Any, op: str, value: Any) -> bool:
    if op == "==":
        return actual == value
    if op == "!=":
        return actual != value
    if actual is None:
        return False
    try:
        if op == ">":
            return actual > value
        if op == ">=":
            return actual >= value
        if op == "<":
            return actual < value
        if op == "<=":
            return actual <= value
    except Exception:
        return False
    raise ValueError(f"unsupported op: {op}")


@dataclass(frozen=True)
class SerializablePredicate:
    kind: str
    data: Dict[str, Any] = field(default_factory=dict)
    children: Tuple["SerializablePredicate", ...] = ()

    def __call__(self, obj: Any) -> bool:
        if self.kind == "tag":
            pattern = str(self.data["pattern"])
            scope = normalize_tag_scope(str(self.data.get("scope", "effective")))
            tags = _get_tags(obj, scope)
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                return any(tag.startswith(prefix) for tag in tags)
            return pattern in tags

        if self.kind == "operation_event":
            track = _lookup_metadata(obj, "track")
            if not isinstance(track, dict):
                return False
            actual_names: set[str] = set()
            for key in ("op", "operation"):
                if track.get(key) is not None:
                    actual_names.update(_operation_names(track[key]))
            if not actual_names.intersection(_operation_names(self.data["op"])):
                return False
            expected = str(self.data.get("event", "*"))
            events = _track_values(track, "events", "event")
            return bool(events) if expected == "*" else expected in events

        if self.kind == "origin_role":
            track = _lookup_metadata(obj, "track")
            if not isinstance(track, dict):
                return False
            roles = _track_values(track, "origin_roles", "origin_role")
            return str(self.data["role"]) in roles

        if self.kind == "output_role":
            track = _lookup_metadata(obj, "track")
            if not isinstance(track, dict):
                return False
            roles = _track_values(track, "result_roles", "result_role")
            return str(self.data["role"]) in roles

        if self.kind in {"source_binding", "source_topology"}:
            list_bindings = getattr(obj, "_local_tag_bindings", None)
            if not callable(list_bindings):
                raise UnsupportedQueryCapabilityError(
                    f"{self.kind} requires canonical local TagBinding evidence"
                )
            field = (
                "source_binding_id"
                if self.kind == "source_binding"
                else "source_topo_id"
            )
            expected = str(self.data[field])
            return any(
                str(binding.evidence.data.get(field, "")) == expected
                for binding in list_bindings()
            )

        if self.kind == "meta":
            actual = _lookup_metadata(obj, str(self.data["path"]))
            return _compare(actual, str(self.data["op"]), self.data["value"])

        if self.kind == "property_compare":
            actual = _lookup_property(obj, str(self.data["path"]))
            if actual is MISSING:
                return False
            return _compare(actual, str(self.data["op"]), self.data["value"])

        if self.kind == "curve_type":
            gtype = _geom_type(obj)
            return gtype == str(self.data["value"]).upper()

        if self.kind == "surface_type":
            gtype = _geom_type(obj)
            return gtype == str(self.data["value"]).upper()

        if self.kind == "and":
            return all(child(obj) for child in self.children)

        if self.kind == "or":
            return any(child(obj) for child in self.children)

        if self.kind == "not":
            return not self.children[0](obj)

        raise ValueError(f"unsupported predicate kind: {self.kind}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "data": dict(self.data),
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SerializablePredicate":
        if not isinstance(data, dict):
            raise ValueError("predicate payload must be an object")
        if set(data) - {"kind", "data", "children"}:
            raise ValueError("predicate payload contains unknown fields")
        kind = data.get("kind")
        raw_data = data.get("data", {})
        raw_children = data.get("children", [])
        if not isinstance(kind, str) or not kind:
            raise ValueError("predicate kind must be a non-empty string")
        if not isinstance(raw_data, dict):
            raise ValueError("predicate data must be an object")
        if not isinstance(raw_children, list):
            raise ValueError("predicate children must be an array")

        schemas = {
            "tag": ({"pattern"}, {"scope"}),
            "operation_event": ({"op"}, {"event"}),
            "origin_role": ({"role"}, set()),
            "output_role": ({"role"}, set()),
            "source_binding": ({"source_binding_id"}, set()),
            "source_topology": ({"source_topo_id"}, set()),
            "meta": ({"path", "op", "value"}, set()),
            "property_compare": ({"path", "op", "value"}, set()),
            "curve_type": ({"value"}, set()),
            "surface_type": ({"value"}, set()),
            "and": (set(), set()),
            "or": (set(), set()),
            "not": (set(), set()),
        }
        if kind not in schemas:
            raise ValueError(f"unsupported predicate kind: {kind}")
        required, optional = schemas[kind]
        missing = required - set(raw_data)
        unknown = set(raw_data) - required - optional
        if missing:
            raise ValueError(
                f"predicate '{kind}' is missing required data: {', '.join(sorted(missing))}"
            )
        if unknown:
            raise ValueError(
                f"predicate '{kind}' contains unknown data: {', '.join(sorted(unknown))}"
            )
        if kind in {"and", "or"} and not raw_children:
            raise ValueError(f"predicate '{kind}' requires at least one child")
        if kind == "not" and len(raw_children) != 1:
            raise ValueError("predicate 'not' requires exactly one child")
        if kind not in {"and", "or", "not"} and raw_children:
            raise ValueError(f"predicate '{kind}' cannot contain children")

        return cls(
            kind=kind,
            data=dict(raw_data),
            children=tuple(
                SerializablePredicate.from_dict(child) for child in raw_children
            ),
        )


@dataclass(frozen=True)
class SerializableKey:
    kind: str
    data: Dict[str, Any] = field(default_factory=dict)

    def __call__(self, obj: Any) -> Any:
        if self.kind == "value":
            path = str(self.data["path"])
            default = self.data.get("default")
            actual = _lookup_metadata(obj, path)
            if actual is not None:
                return actual

            if path.startswith("geo."):
                remainder = path.split(".", 1)[1]
                if "." not in remainder:
                    if remainder == "area" and hasattr(obj, "get_area"):
                        try:
                            return obj.get_area()
                        except Exception:
                            return default
                    if remainder == "length" and hasattr(obj, "get_length"):
                        try:
                            return obj.get_length()
                        except Exception:
                            return default
                    if remainder == "volume" and hasattr(obj, "get_volume"):
                        try:
                            return obj.get_volume()
                        except Exception:
                            return default
            return default

        if self.kind == "property":
            path = str(self.data["path"])
            default = self.data.get("default")
            actual = _lookup_property(obj, path)
            if actual is MISSING:
                return default
            return actual

        if self.kind == "center_axis":
            center = _center_tuple(obj)
            if center is None:
                return None
            axis = str(self.data["axis"]).lower()
            if axis == "x":
                return center[0]
            if axis == "y":
                return center[1]
            if axis == "z":
                return center[2]
            raise ValueError(f"unsupported axis: {axis}")

        raise ValueError(f"unsupported key kind: {self.kind}")

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "data": dict(self.data)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SerializableKey":
        return cls(kind=str(data["kind"]), data=dict(data.get("data", {})))


@dataclass(frozen=True)
class TraversalSpec:
    relation: str

    def to_dict(self) -> Dict[str, Any]:
        return {"relation": self.relation}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraversalSpec":
        return cls(relation=str(data["relation"]))


@dataclass(frozen=True)
class ShapeSelector:
    target_kind: str
    source_selector: Optional["ShapeSelector"] = None
    traversal: Optional[TraversalSpec] = None
    predicate: Optional[SerializablePredicate] = None
    order_key: Optional[SerializableKey] = None
    order_keys: Tuple[Tuple[SerializableKey, bool], ...] = ()
    order_desc: bool = False
    limit_count: Optional[int] = None
    cardinality: Dict[str, int] = field(default_factory=dict)
    source_node_id: Optional[str] = None
    source_output_slot: Optional[int] = None
    set_operation: Optional[str] = None
    operands: Tuple["ShapeSelector", ...] = ()
    incident_face_selectors: Tuple["ShapeSelector", ...] = ()
    incident_faces_distinct: bool = False
    incident_face_cardinality: Dict[str, int] = field(default_factory=dict)

    def where(self, predicate: SerializablePredicate) -> "ShapeSelector":
        if not isinstance(predicate, SerializablePredicate):
            raise TypeError(
                "ShapeSelector.where only supports serializable QL predicates"
            )
        if self.predicate is None:
            combined = predicate
        else:
            combined = and_(self.predicate, predicate)
            if not isinstance(combined, SerializablePredicate):
                raise TypeError("combined predicate must be serializable")
        return ShapeSelector(
            target_kind=self.target_kind,
            source_selector=self.source_selector,
            traversal=self.traversal,
            predicate=combined,
            order_key=self.order_key,
            order_keys=tuple(self.order_keys),
            order_desc=self.order_desc,
            limit_count=self.limit_count,
            cardinality=dict(self.cardinality),
            source_node_id=self.source_node_id,
            source_output_slot=self.source_output_slot,
            set_operation=self.set_operation,
            operands=tuple(self.operands),
            incident_face_selectors=tuple(self.incident_face_selectors),
            incident_faces_distinct=self.incident_faces_distinct,
            incident_face_cardinality=dict(self.incident_face_cardinality),
        )

    def order_by(self, key: SerializableKey, desc: bool = False) -> "ShapeSelector":
        if not isinstance(key, SerializableKey):
            raise TypeError("ShapeSelector.order_by only supports serializable QL keys")
        order_keys = (*self.order_keys, (key, bool(desc)))
        return ShapeSelector(
            target_kind=self.target_kind,
            source_selector=self.source_selector,
            traversal=self.traversal,
            predicate=self.predicate,
            order_key=key,
            order_keys=order_keys,
            order_desc=bool(desc),
            limit_count=self.limit_count,
            cardinality=dict(self.cardinality),
            source_node_id=self.source_node_id,
            source_output_slot=self.source_output_slot,
            set_operation=self.set_operation,
            operands=tuple(self.operands),
            incident_face_selectors=tuple(self.incident_face_selectors),
            incident_faces_distinct=self.incident_faces_distinct,
            incident_face_cardinality=dict(self.incident_face_cardinality),
        )

    def from_source(
        self, node_id: str, output_slot: int = 0
    ) -> "ShapeSelector":
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("node_id must be a non-empty string")
        if output_slot < 0:
            raise ValueError("output_slot must be >= 0")
        return ShapeSelector(
            target_kind=self.target_kind,
            source_selector=self.source_selector,
            traversal=self.traversal,
            predicate=self.predicate,
            order_key=self.order_key,
            order_keys=tuple(self.order_keys),
            order_desc=self.order_desc,
            limit_count=self.limit_count,
            cardinality=dict(self.cardinality),
            source_node_id=node_id,
            source_output_slot=int(output_slot),
            set_operation=self.set_operation,
            operands=tuple(self.operands),
            incident_face_selectors=tuple(self.incident_face_selectors),
            incident_faces_distinct=self.incident_faces_distinct,
            incident_face_cardinality=dict(self.incident_face_cardinality),
        )

    def take(self, count: int) -> "ShapeSelector":
        if count < 0:
            raise ValueError("count must be >= 0")
        return ShapeSelector(
            target_kind=self.target_kind,
            source_selector=self.source_selector,
            traversal=self.traversal,
            predicate=self.predicate,
            order_key=self.order_key,
            order_keys=tuple(self.order_keys),
            order_desc=self.order_desc,
            limit_count=int(count),
            cardinality=dict(self.cardinality),
            source_node_id=self.source_node_id,
            source_output_slot=self.source_output_slot,
            set_operation=self.set_operation,
            operands=tuple(self.operands),
            incident_face_selectors=tuple(self.incident_face_selectors),
            incident_faces_distinct=self.incident_faces_distinct,
            incident_face_cardinality=dict(self.incident_face_cardinality),
        )

    def exactly(self, count: int) -> "ShapeSelector":
        if count < 0:
            raise ValueError("count must be >= 0")
        card = dict(self.cardinality)
        card["exactly"] = int(count)
        return ShapeSelector(
            target_kind=self.target_kind,
            source_selector=self.source_selector,
            traversal=self.traversal,
            predicate=self.predicate,
            order_key=self.order_key,
            order_keys=tuple(self.order_keys),
            order_desc=self.order_desc,
            limit_count=self.limit_count,
            cardinality=card,
            source_node_id=self.source_node_id,
            source_output_slot=self.source_output_slot,
            set_operation=self.set_operation,
            operands=tuple(self.operands),
            incident_face_selectors=tuple(self.incident_face_selectors),
            incident_faces_distinct=self.incident_faces_distinct,
            incident_face_cardinality=dict(self.incident_face_cardinality),
        )

    def at_least(self, count: int) -> "ShapeSelector":
        if count < 0:
            raise ValueError("count must be >= 0")
        card = dict(self.cardinality)
        card["at_least"] = int(count)
        return ShapeSelector(
            target_kind=self.target_kind,
            source_selector=self.source_selector,
            traversal=self.traversal,
            predicate=self.predicate,
            order_key=self.order_key,
            order_keys=tuple(self.order_keys),
            order_desc=self.order_desc,
            limit_count=self.limit_count,
            cardinality=card,
            source_node_id=self.source_node_id,
            source_output_slot=self.source_output_slot,
            set_operation=self.set_operation,
            operands=tuple(self.operands),
            incident_face_selectors=tuple(self.incident_face_selectors),
            incident_faces_distinct=self.incident_faces_distinct,
            incident_face_cardinality=dict(self.incident_face_cardinality),
        )

    def at_most(self, count: int) -> "ShapeSelector":
        if count < 0:
            raise ValueError("count must be >= 0")
        card = dict(self.cardinality)
        card["at_most"] = int(count)
        return ShapeSelector(
            target_kind=self.target_kind,
            source_selector=self.source_selector,
            traversal=self.traversal,
            predicate=self.predicate,
            order_key=self.order_key,
            order_keys=tuple(self.order_keys),
            order_desc=self.order_desc,
            limit_count=self.limit_count,
            cardinality=card,
            source_node_id=self.source_node_id,
            source_output_slot=self.source_output_slot,
            set_operation=self.set_operation,
            operands=tuple(self.operands),
            incident_face_selectors=tuple(self.incident_face_selectors),
            incident_faces_distinct=self.incident_faces_distinct,
            incident_face_cardinality=dict(self.incident_face_cardinality),
        )

    def traverse(self, relation: str, to_kind: str) -> "ShapeSelector":
        relation = str(relation).strip().lower()
        to_kind = str(to_kind).strip().lower()
        if relation != "boundary":
            raise ValueError(f"unsupported traversal relation: {relation}")
        if to_kind not in {"vertex", "edge", "wire", "face", "solid", "compound"}:
            raise ValueError(f"unsupported traversal target kind: {to_kind}")
        return ShapeSelector(
            target_kind=to_kind,
            source_selector=self,
            traversal=TraversalSpec(relation=relation),
            source_node_id=self.source_node_id,
            source_output_slot=self.source_output_slot,
        )

    def boundary(self, to_kind: str) -> "ShapeSelector":
        return self.traverse("boundary", to_kind)

    def intersection(self, other: "ShapeSelector") -> "ShapeSelector":
        """Return entities present in both selector result sets."""

        if not isinstance(other, ShapeSelector):
            raise TypeError("intersection requires another ShapeSelector")
        if self.target_kind != other.target_kind:
            raise ValueError("intersection operands must select the same topology kind")
        return ShapeSelector(
            target_kind=self.target_kind,
            set_operation="intersection",
            operands=(self, other),
        )

    def shared_boundary(
        self, other: "ShapeSelector", to_kind: str = "edge"
    ) -> "ShapeSelector":
        """Select current-topology boundary entities shared by both operands."""

        return self.boundary(to_kind).intersection(other.boundary(to_kind))

    def incident_to(
        self,
        *face_selectors: "ShapeSelector",
        distinct: bool = False,
    ) -> "ShapeSelector":
        """Restrict Edges by their distinct incident Face witnesses."""

        if self.target_kind != "edge":
            raise ValueError("incident_to is only valid on an Edge selector")
        if not face_selectors or not all(
            isinstance(selector, ShapeSelector) and selector.target_kind == "face"
            for selector in face_selectors
        ):
            raise TypeError("incident_to requires one or more Face selectors")
        return ShapeSelector(
            target_kind="edge",
            source_selector=self.source_selector,
            traversal=self.traversal,
            predicate=self.predicate,
            order_key=self.order_key,
            order_keys=tuple(self.order_keys),
            order_desc=self.order_desc,
            limit_count=self.limit_count,
            cardinality=dict(self.cardinality),
            source_node_id=self.source_node_id,
            source_output_slot=self.source_output_slot,
            set_operation=self.set_operation,
            operands=tuple(self.operands),
            incident_face_selectors=tuple(face_selectors),
            incident_faces_distinct=bool(distinct),
            incident_face_cardinality=dict(self.incident_face_cardinality),
        )

    def incident_face_count(self, *, exactly: int) -> "ShapeSelector":
        if self.target_kind != "edge":
            raise ValueError("incident_face_count is only valid on an Edge selector")
        if exactly < 0:
            raise ValueError("incident face count must be >= 0")
        return ShapeSelector(
            target_kind="edge",
            source_selector=self.source_selector,
            traversal=self.traversal,
            predicate=self.predicate,
            order_key=self.order_key,
            order_keys=tuple(self.order_keys),
            order_desc=self.order_desc,
            limit_count=self.limit_count,
            cardinality=dict(self.cardinality),
            source_node_id=self.source_node_id,
            source_output_slot=self.source_output_slot,
            set_operation=self.set_operation,
            operands=tuple(self.operands),
            incident_face_selectors=tuple(self.incident_face_selectors),
            incident_faces_distinct=self.incident_faces_distinct,
            incident_face_cardinality={"exactly": int(exactly)},
        )

    def resolve(self, scope: Any) -> List[Any]:
        if self.set_operation is not None:
            if self.set_operation != "intersection" or len(self.operands) < 2:
                raise ValueError(f"unsupported selector set operation: {self.set_operation}")
            operand_items = [operand.resolve(scope) for operand in self.operands]
            shared = [
                {_shape_identity(item) for item in items}
                for items in operand_items[1:]
            ]
            items = [
                item
                for item in operand_items[0]
                if all(_shape_identity(item) in markers for markers in shared)
            ]
        elif self.source_selector is None:
            items = _resolve_scope_items(scope, self.target_kind)
        else:
            if self.traversal is None:
                raise ValueError("traversal selector is missing traversal metadata")
            items = _traverse_items(
                self.source_selector.resolve(scope),
                self.traversal,
                self.target_kind,
            )
        if self.predicate is not None:
            items = [item for item in items if self.predicate(item)]

        if self.incident_face_selectors:
            face_sets = [
                {
                    _shape_identity(face)
                    for face in selector.resolve(scope)
                }
                for selector in self.incident_face_selectors
            ]

            def has_incident_witnesses(edge: Any) -> bool:
                incident = getattr(edge, "get_incident_faces", lambda: [])()
                incident_ids = [_shape_identity(face) for face in incident]
                if self.incident_faces_distinct:
                    return _has_distinct_witnesses(incident_ids, face_sets)
                return all(
                    any(face_id in face_set for face_id in incident_ids)
                    for face_set in face_sets
                )

            items = [item for item in items if has_incident_witnesses(item)]

        if self.incident_face_cardinality:
            exact_incident = self.incident_face_cardinality.get("exactly")
            if exact_incident is not None:
                items = [
                    item
                    for item in items
                    if len(
                        {
                            _shape_identity(face)
                            for face in getattr(item, "get_incident_faces", lambda: [])()
                        }
                    )
                    == exact_incident
                ]

        order_specs = self.order_keys
        if not order_specs and self.order_key is not None:
            order_specs = ((self.order_key, self.order_desc),)
        for order_key, desc in reversed(order_specs):
            def _safe_key(obj: Any, key_fn: SerializableKey = order_key):
                value = key_fn(obj)
                return (value is None, value)

            items = sorted(items, key=_safe_key, reverse=desc)

        if self.limit_count is not None:
            items = items[: self.limit_count]

        exact = self.cardinality.get("exactly")
        if exact is not None and len(items) != exact:
            self._raise_cardinality_failure(items, expected=exact, mode="exactly", scope=scope)
        at_least = self.cardinality.get("at_least")
        if at_least is not None and len(items) < at_least:
            self._raise_cardinality_failure(items, expected=at_least, mode="at_least", scope=scope)
        at_most = self.cardinality.get("at_most")
        if at_most is not None and len(items) > at_most:
            self._raise_cardinality_failure(items, expected=at_most, mode="at_most", scope=scope)
        return list(items)

    def _raise_cardinality_failure(
        self, items: List[Any], *, expected: int, mode: str, scope: Any
    ) -> NoReturn:
        """Cardinality violation with inventory, logical-surface grouping, evidence.

        The agent-facing contract: name what matched (hit), what actually
        exists (near_miss), whether matched faces are one logical surface
        split by a seam, and one rendered evidence view of the scope. The
        diagnosis itself must never mask the failure — on any internal error
        the plain cardinality ValueError is raised instead.
        """

        try:
            self._cardinality_failure(items, expected=expected, mode=mode, scope=scope)
        except SimpleCADError:
            raise
        except Exception as fallback:
            raise ValueError(
                f"QL selector expected {mode} {expected} {self.target_kind}(s), "
                f"got {len(items)}"
            ) from fallback

    def _cardinality_failure(
        self, items: List[Any], *, expected: int, mode: str, scope: Any
    ) -> NoReturn:
        candidates = _resolve_scope_items(scope, self.target_kind)
        prefix = _QL_SYMBOL_PREFIX.get(self.target_kind, self.target_kind[0].upper())
        matched_ids = {_shape_identity(item) for item in items}

        # Symbol numbering follows the candidate enumeration, so hits and
        # near-misses share one stable naming for this scope.
        inventory: List[InventoryEntry] = []
        hit_positions: Dict[int, Any] = {}
        near_miss_count = 0
        for index, item in enumerate(candidates):
            is_hit = _shape_identity(item) in matched_ids
            if is_hit:
                hit_positions[index] = item
            else:
                if near_miss_count >= 8:
                    continue
                near_miss_count += 1
            inventory.append(
                InventoryEntry(
                    symbol=f"{prefix}{index + 1}",
                    status="hit" if is_hit else "near_miss",
                    description=_entity_geometry_summary(item),
                )
            )

        groups = (
            _face_logical_groups(items)
            if self.target_kind == "face" and len(items) > 1
            else []
        )

        measurements = [
            ErrorMeasurement("matched_count", float(len(items)), ""),
            ErrorMeasurement("candidate_count", float(len(candidates)), ""),
            ErrorMeasurement("expected_count", float(expected), ""),
        ]

        # Logical groups index into `items`; symbols come from the candidate
        # enumeration, so map each grouped item to its candidate index first.
        candidate_index_of_item = {
            _shape_identity(item): index for index, item in enumerate(candidates)
        }

        repair: List[str] = []
        if len(items) > expected and groups:
            group_symbols = []
            for group in groups:
                candidate_indices = [
                    candidate_index_of_item[_shape_identity(items[position])]
                    for position in group
                ]
                if all(index in hit_positions for index in candidate_indices):
                    group_symbols.append(
                        "+".join(f"{prefix}{index + 1}" for index in candidate_indices)
                    )
            if group_symbols:
                repair.append(
                    f"{', '.join(group_symbols)} lie on one logical surface split by "
                    "a seam — select the whole group (drop the exactly(1) assertion) "
                    "or target it via a role tag."
                )
        if len(items) > expected:
            repair.append(
                "Tighten the predicate (position/axis/tag constraints) or take an "
                "explicit member with .first()/.take(n) instead of exactly()."
            )
        if len(items) < expected:
            repair.append(
                "No entity satisfies the full predicate; the near-miss inventory "
                "above lists what actually exists — align predicate values with "
                "those measured geometries."
            )
            repair.append(
                "Booleans and fillets re-split topology; re-derive the selector "
                "from the newest shape instead of reusing one resolved earlier."
            )

        near_misses = [
            item
            for item in candidates
            if _shape_identity(item) not in matched_ids
        ][:3]
        evidence = _ql_evidence(
            scope, items, self.target_kind,
            dedup_key=("ql", self.target_kind, mode, expected, len(items)),
            near_misses=near_misses,
        )

        what = (
            f"QL selector expected {mode.replace('_', ' ')} {expected} "
            f"{self.target_kind}(s), got {len(items)}"
        )
        if groups:
            what += (
                f"; the matched faces include {len(groups)} logical surface group(s) "
                "split by seams"
            )
        raise_harness_error(
            operation=f"ql.{self.target_kind}.resolve",
            what_happened=what,
            possible_causes=[
                "The predicate does not match the actual geometry values.",
                "OCCT split one logical face into several at a seam after a boolean.",
                "The selector was resolved against an older shape state.",
            ],
            how_to_fix=[
                "Read the inventory: hit = matched, near_miss = what exists instead.",
                "Re-derive selectors from the newest shape after topology-changing ops.",
            ],
            measurements=measurements,
            evidence=evidence,
            repair=repair,
            inventory=inventory,
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "target_kind": self.target_kind,
            "order_desc": self.order_desc,
            "cardinality": dict(self.cardinality),
        }
        if self.source_selector is not None:
            payload["source"] = self.source_selector.to_dict()
        if self.traversal is not None:
            payload["traversal"] = self.traversal.to_dict()
        if self.predicate is not None:
            payload["predicate"] = self.predicate.to_dict()
        if self.order_key is not None:
            payload["order_key"] = self.order_key.to_dict()
        if self.order_keys:
            payload["order_keys"] = [
                {"key": key.to_dict(), "desc": desc}
                for key, desc in self.order_keys
            ]
        if self.limit_count is not None:
            payload["limit"] = self.limit_count
        if self.source_node_id is not None:
            payload["source_node_id"] = self.source_node_id
            payload["source_output_slot"] = int(self.source_output_slot or 0)
        if self.set_operation is not None:
            payload["set_operation"] = {
                "op": self.set_operation,
                "operands": [operand.to_dict() for operand in self.operands],
            }
        if self.incident_face_selectors:
            payload["incident_faces"] = {
                "selectors": [selector.to_dict() for selector in self.incident_face_selectors],
                "distinct": self.incident_faces_distinct,
            }
        if self.incident_face_cardinality:
            payload["incident_face_cardinality"] = dict(self.incident_face_cardinality)
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShapeSelector":
        set_operation = None
        operands: Tuple[ShapeSelector, ...] = ()
        incident_face_selectors: Tuple[ShapeSelector, ...] = ()
        incident_faces_distinct = False
        incident_face_cardinality: Dict[str, int] = {}
        raw_set_operation = data.get("set_operation")
        if raw_set_operation is not None:
            if not isinstance(raw_set_operation, dict):
                raise ValueError("selector set_operation must be an object")
            if set(raw_set_operation) != {"op", "operands"}:
                raise ValueError("selector set_operation has invalid fields")
            set_operation = str(raw_set_operation["op"]).strip().lower()
            if set_operation != "intersection":
                raise ValueError(f"unsupported selector set operation: {set_operation}")
            raw_operands = raw_set_operation["operands"]
            if not isinstance(raw_operands, list) or len(raw_operands) < 2:
                raise ValueError("selector intersection requires at least two operands")
            operands = tuple(ShapeSelector.from_dict(item) for item in raw_operands)
            target_kind = str(data["target_kind"])
            if any(operand.target_kind != target_kind for operand in operands):
                raise ValueError("selector intersection operands must match target_kind")
        raw_incident = data.get("incident_faces")
        if raw_incident is not None:
            if not isinstance(raw_incident, dict) or set(raw_incident) != {
                "selectors", "distinct"
            }:
                raise ValueError("selector incident_faces has invalid fields")
            if str(data.get("target_kind", "")).lower() != "edge":
                raise ValueError("incident_faces is only valid for edge selectors")
            raw_selectors = raw_incident["selectors"]
            if not isinstance(raw_selectors, list) or not raw_selectors:
                raise ValueError("incident_faces requires one or more selectors")
            incident_face_selectors = tuple(
                ShapeSelector.from_dict(item) for item in raw_selectors
            )
            if any(selector.target_kind != "face" for selector in incident_face_selectors):
                raise ValueError("incident_faces selectors must select faces")
            incident_faces_distinct = bool(raw_incident["distinct"])
        raw_incident_cardinality = data.get("incident_face_cardinality")
        if raw_incident_cardinality is not None:
            if not isinstance(raw_incident_cardinality, dict) or set(
                raw_incident_cardinality
            ) != {"exactly"}:
                raise ValueError("incident_face_cardinality only supports exactly")
            incident_face_cardinality = {
                "exactly": int(raw_incident_cardinality["exactly"])
            }
        source_selector = None
        if isinstance(data.get("source"), dict):
            source_selector = ShapeSelector.from_dict(data["source"])
        traversal = None
        if isinstance(data.get("traversal"), dict):
            traversal = TraversalSpec.from_dict(data["traversal"])
        predicate = None
        if isinstance(data.get("predicate"), dict):
            predicate = SerializablePredicate.from_dict(data["predicate"])
        order_key = None
        if isinstance(data.get("order_key"), dict):
            order_key = SerializableKey.from_dict(data["order_key"])
        order_keys: Tuple[Tuple[SerializableKey, bool], ...] = ()
        if isinstance(data.get("order_keys"), list):
            parsed_order_keys = []
            for item in data["order_keys"]:
                if not isinstance(item, dict) or not isinstance(item.get("key"), dict):
                    raise ValueError("selector order_keys entries must contain a key object")
                parsed_order_keys.append(
                    (SerializableKey.from_dict(item["key"]), bool(item.get("desc", False)))
                )
            order_keys = tuple(parsed_order_keys)
            if order_key is None and order_keys:
                order_key = order_keys[-1][0]
        elif order_key is not None:
            order_keys = ((order_key, bool(data.get("order_desc", False))),)
        return cls(
            target_kind=str(data["target_kind"]),
            source_selector=source_selector,
            traversal=traversal,
            predicate=predicate,
            order_key=order_key,
            order_keys=order_keys,
            order_desc=bool(data.get("order_desc", False)),
            limit_count=(int(data["limit"]) if data.get("limit") is not None else None),
            cardinality=dict(data.get("cardinality", {})),
            source_node_id=(
                str(data["source_node_id"])
                if data.get("source_node_id") is not None
                else None
            ),
            source_output_slot=(
                int(data.get("source_output_slot", 0))
                if data.get("source_node_id") is not None
                else None
            ),
            set_operation=set_operation,
            operands=operands,
            incident_face_selectors=incident_face_selectors,
            incident_faces_distinct=incident_faces_distinct,
            incident_face_cardinality=incident_face_cardinality,
        )


def _has_distinct_witnesses(
    incident_ids: Sequence[Any], candidate_sets: Sequence[set[Any]]
) -> bool:
    """Return whether each relation has a distinct incident-face witness."""

    used: set[Any] = set()

    def visit(index: int) -> bool:
        if index == len(candidate_sets):
            return True
        for face_id in incident_ids:
            if face_id in used or face_id not in candidate_sets[index]:
                continue
            used.add(face_id)
            if visit(index + 1):
                return True
            used.remove(face_id)
        return False

    return visit(0)


def _shape_identity(obj: Any) -> Any:
    entity = getattr(obj, "_entity", None)
    if entity is not None:
        return (obj.__class__.__name__, id(entity))
    topo_id = getattr(obj, "topo_id", None)
    if topo_id is not None:
        return (obj.__class__.__name__, topo_id)

    topo_ref = None
    if hasattr(obj, "get_metadata"):
        try:
            topo_ref = obj.get_metadata("topo_ref")
        except Exception:
            topo_ref = None
    if isinstance(topo_ref, dict):
        ref_topo_id = topo_ref.get("topo_id")
        kind = topo_ref.get("kind")
        if ref_topo_id is not None:
            return (kind, ref_topo_id)

    return id(obj)


def _dedupe_items(items: Iterable[Any]) -> List[Any]:
    result: List[Any] = []
    seen = set()
    for item in items:
        marker = _shape_identity(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _boundary_items(scope: Any, target_kind: str) -> List[Any]:
    cls_name = scope.__class__.__name__

    if target_kind == "face":
        if hasattr(scope, "get_faces"):
            return list(scope._iter_faces())
        return []

    if target_kind == "wire":
        if cls_name == "Face":
            wires = []
            if hasattr(scope, "get_outer_wire"):
                wires.append(scope.get_outer_wire())
            if hasattr(scope, "get_inner_wires"):
                wires.extend(scope._iter_inner_wires())
            return wires
        if hasattr(scope, "get_faces"):
            wires = []
            for face in scope._iter_faces():
                wires.extend(_boundary_items(face, "wire"))
            return _dedupe_items(wires)
        if hasattr(scope, "get_children"):
            return [
                child
                for child in scope.get_children()
                if child.__class__.__name__ == "Wire"
            ]
        return []

    if target_kind == "edge":
        if cls_name == "Face":
            edges = []
            for wire in _boundary_items(scope, "wire"):
                if hasattr(wire, "get_edges"):
                    edges.extend(wire._iter_edges())
            return _dedupe_items(edges)
        if hasattr(scope, "get_edges"):
            return _dedupe_items(scope._iter_edges())
        if hasattr(scope, "get_faces"):
            edges = []
            for face in scope._iter_faces():
                edges.extend(_boundary_items(face, "edge"))
            return _dedupe_items(edges)
        return []

    if target_kind == "vertex":
        if cls_name == "Edge" and hasattr(scope, "get_children"):
            return [
                child
                for child in scope.get_children()
                if child.__class__.__name__ == "Vertex"
            ]
        if target_kind == "vertex" and hasattr(scope, "get_edges"):
            vertices = []
            for edge in _boundary_items(scope, "edge"):
                vertices.extend(_boundary_items(edge, "vertex"))
            return _dedupe_items(vertices)
        return []

    if target_kind == "solid":
        if cls_name == "Compound" and hasattr(scope, "get_solids"):
            return list(scope._iter_solids())
        return [scope] if cls_name == "Solid" else []

    if target_kind == "shell":
        if cls_name == "Compound" and hasattr(scope, "get_children"):
            return [
                child
                for child in scope.get_children()
                if child.__class__.__name__ == "Shell"
            ]
        return [scope] if cls_name == "Shell" else []

    if target_kind == "compound":
        return [scope] if cls_name == "Compound" else []

    return []


def _traverse_items(
    items: Sequence[Any], traversal: TraversalSpec, target_kind: str
) -> List[Any]:
    if traversal.relation != "boundary":
        raise ValueError(f"unsupported traversal relation: {traversal.relation}")

    traversed: List[Any] = []
    for item in items:
        traversed.extend(_boundary_items(item, target_kind))
    return _dedupe_items(traversed)


# Inventory symbol prefixes — one letter per target kind, so error text and
# rendered evidence can reference the same entity ("F3", "E7") unambiguously.
_QL_SYMBOL_PREFIX = {
    "face": "F",
    "edge": "E",
    "vertex": "V",
    "shell": "S",
    "wire": "W",
    "body": "B",
}


def _entity_geometry_summary(item: Any) -> str:
    """Short geometry description for inventory entries; never raises.

    Faces carry surface parameters plus the bounding-box span along the
    dominant axis, so two pieces of one split surface (identical parameters)
    remain distinguishable in text alone.
    """

    try:
        from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
        from OCP.GeomAbs import (
            GeomAbs_Circle,
            GeomAbs_Cone,
            GeomAbs_Cylinder,
            GeomAbs_Line,
            GeomAbs_Plane,
            GeomAbs_Sphere,
            GeomAbs_Torus,
        )
        from OCP.TopoDS import TopoDS

        kind = item.__class__.__name__.lower()
        if kind == "face":
            adaptor = BRepAdaptor_Surface(TopoDS.Face_s(item.wrapped))
            surface_type = adaptor.GetType()
            summary: str
            if surface_type == GeomAbs_Plane:
                direction = adaptor.Plane().Axis().Direction()
                summary = (
                    "plane, normal "
                    f"({direction.X():.3g}, {direction.Y():.3g}, {direction.Z():.3g})"
                )
            elif surface_type == GeomAbs_Cylinder:
                cylinder = adaptor.Cylinder()
                axis = cylinder.Axis().Direction()
                location = cylinder.Location()
                summary = (
                    f"cylinder r={cylinder.Radius():.4g}, axis "
                    f"({axis.X():.2g},{axis.Y():.2g},{axis.Z():.2g}) @ "
                    f"({location.X():.3g},{location.Y():.3g},{location.Z():.3g})"
                )
            elif surface_type == GeomAbs_Cone:
                cone = adaptor.Cone()
                summary = (
                    f"cone half-angle {_deg(cone.SemiAngle()):.3g} deg, "
                    f"r_ref={cone.RefRadius():.4g}"
                )
            elif surface_type == GeomAbs_Sphere:
                summary = f"sphere r={adaptor.Sphere().Radius():.4g}"
            elif surface_type == GeomAbs_Torus:
                torus = adaptor.Torus()
                summary = (
                    f"torus R={torus.MajorRadius():.4g}, "
                    f"r={torus.MinorRadius():.4g}"
                )
            else:
                summary = "freeform surface"
                return f"{summary}, spans {_face_span(item)}"
            # Rotational surfaces: report the span along the surface axis —
            # the coordinate that distinguishes split pieces of one surface.
            axis = None
            if surface_type == GeomAbs_Cylinder:
                axis = adaptor.Cylinder().Axis().Direction()
            elif surface_type == GeomAbs_Cone:
                axis = adaptor.Cone().Axis().Direction()
            return f"{summary}, spans {_face_span(item, axis)}"
        if kind == "edge":
            adaptor = BRepAdaptor_Curve(TopoDS.Edge_s(item.wrapped))
            curve_type = adaptor.GetType()
            length = float(item.get_length())
            if curve_type == GeomAbs_Line:
                return f"line, length {length:.4g} mm"
            if curve_type == GeomAbs_Circle:
                return f"circular arc r={adaptor.Circle().Radius():.4g}, length {length:.4g} mm"
            return f"curve, length {length:.4g} mm"
        if kind == "vertex":
            x, y, z = item.get_coordinates()
            return f"({x:.4g}, {y:.4g}, {z:.4g})"
        return kind
    except Exception:
        return item.__class__.__name__


def _face_span(face: Any, axis: Any = None) -> str:
    """Bounding-box extent as a short text range, preferring the surface axis.

    ``spans z=[0, 7]`` distinguishes two pieces of one split surface that
    otherwise share identical surface parameters; for rotational surfaces the
    axis direction is the discriminating coordinate, for other faces the
    longest bounding-box axis is used.
    """

    try:
        from .kernel.ocp_properties import bounding_box

        box = bounding_box(face.wrapped)
        ranges = {
            "x": (box.xmin, box.xmax),
            "y": (box.ymin, box.ymax),
            "z": (box.zmin, box.zmax),
        }
        if axis is not None:
            components = (axis.X(), axis.Y(), axis.Z())
            index = max(range(3), key=lambda i: abs(components[i]))
            name = ("x", "y", "z")[index]
        else:
            name, _range = max(
                ranges.items(), key=lambda item: item[1][1] - item[1][0]
            )
        low, high = ranges[name]
        return f"{name}=[{low:.4g}, {high:.4g}]"
    except Exception:
        return "n/a"


def _deg(radians: float) -> float:
    """Radians to degrees (kept local so callers stay import-light)."""

    import math as _math

    return _math.degrees(radians)


def _faces_same_surface(face_a: Any, face_b: Any) -> bool:
    """True when two faces lie on the same underlying quadric surface."""

    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import (
            GeomAbs_Cone,
            GeomAbs_Cylinder,
            GeomAbs_Plane,
            GeomAbs_Sphere,
            GeomAbs_Torus,
        )
        from OCP.TopoDS import TopoDS

        adaptor_a = BRepAdaptor_Surface(TopoDS.Face_s(face_a.wrapped))
        adaptor_b = BRepAdaptor_Surface(TopoDS.Face_s(face_b.wrapped))
        type_a, type_b = adaptor_a.GetType(), adaptor_b.GetType()
        if type_a != type_b:
            return False
        if type_a == GeomAbs_Plane:
            plane_a, plane_b = adaptor_a.Plane(), adaptor_b.Plane()
            normal_a = plane_a.Axis().Direction()
            normal_b = plane_b.Axis().Direction()
            parallel = abs(normal_a.Dot(normal_b))
            if parallel < 0.999:
                return False
            origin_b = plane_b.Location()
            return abs(plane_a.Distance(origin_b)) < 1e-6
        if type_a == GeomAbs_Cylinder:
            cyl_a, cyl_b = adaptor_a.Cylinder(), adaptor_b.Cylinder()
            if abs(cyl_a.Radius() - cyl_b.Radius()) > 1e-7:
                return False
            axis_a, axis_b = cyl_a.Axis(), cyl_b.Axis()
            if abs(axis_a.Direction().Dot(axis_b.Direction())) < 0.999:
                return False
            # Distance from axis_b's location to axis_a's line: the offset of
            # (location - origin) perpendicular to the shared direction.
            import math as _math

            origin_a = axis_a.Location()
            point_b = axis_b.Location()
            delta = (
                point_b.X() - origin_a.X(),
                point_b.Y() - origin_a.Y(),
                point_b.Z() - origin_a.Z(),
            )
            direction = axis_a.Direction()
            along = (
                delta[0] * direction.X()
                + delta[1] * direction.Y()
                + delta[2] * direction.Z()
            )
            offset_squared = (
                (delta[0] - along * direction.X()) ** 2
                + (delta[1] - along * direction.Y()) ** 2
                + (delta[2] - along * direction.Z()) ** 2
            )
            return _math.sqrt(offset_squared) < 1e-6
        if type_a == GeomAbs_Sphere:
            center_a = adaptor_a.Sphere().Location()
            center_b = adaptor_b.Sphere().Location()
            radius_a = adaptor_a.Sphere().Radius()
            return (
                center_a.Distance(center_b) < 1e-6
                and abs(radius_a - adaptor_b.Sphere().Radius()) < 1e-7
            )
        if type_a in (GeomAbs_Cone, GeomAbs_Torus):
            # Same handle identity is the reliable check; parameter comparison
            # for cones/tori is not needed for the seam-split cases.
            from OCP.BRep import BRep_Tool

            return BRep_Tool.Surface_s(face_a.wrapped) is BRep_Tool.Surface_s(face_b.wrapped)
        return False
    except Exception:
        return False


def _face_logical_groups(faces: List[Any]) -> List[List[int]]:
    """Group face indices that lie on one underlying surface.

    These are logical faces OCCT split at seams, splitter edges, or removed
    regions — the classic "the cylinder side is two faces today, one
    tomorrow" trap. Pieces need not be adjacent to belong to one logical
    surface.
    """

    parent = list(range(len(faces)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for i in range(len(faces)):
        for j in range(i + 1, len(faces)):
            if _faces_same_surface(faces[i], faces[j]):
                root_i, root_j = find(i), find(j)
                if root_i != root_j:
                    parent[root_i] = root_j

    groups: Dict[int, List[int]] = {}
    for index in range(len(faces)):
        groups.setdefault(find(index), []).append(index)
    return [members for members in groups.values() if len(members) > 1]


_MATCHED_TAG = "diagnostic.matched"
_NEAR_MISS_TAG = "diagnostic.near_miss"


def _ql_evidence(
    scope: Any,
    items: List[Any],
    target_kind: str,
    *,
    dedup_key: tuple,
    near_misses: Optional[List[Any]] = None,
) -> List[ErrorEvidence]:
    """Render the scope with the matched entities visibly highlighted.

    Face selections render a wrapper copy of the scope whose matched faces
    carry ``diagnostic.matched`` (orange) and up to three near-miss faces
    carry ``diagnostic.near_miss`` (purple) — the designed highlight channel
    with legend and callouts, so the agent can SEE what it selected. Wrapper
    copies never pollute the user's original shape with tags. Other target
    kinds fall back to tagged marker tubes along the matched entities.
    """

    try:
        from .operators._diagnostics import (
            _solid_copy,
            render_failure_evidence,
        )

        highlight_tags: List[str] = []
        tag_labels: Dict[str, str] = {}
        shapes: List[Any] = []

        if target_kind == "face":
            copy = _solid_copy(scope)
            if copy is not None:
                # Match by kernel topology identity (IsSame): Python-level
                # shape ids differ across wrapper copies, TopoDS identity
                # does not.
                matched_wrapped = [item.wrapped for item in items]
                near_wrapped = [item.wrapped for item in (near_misses or [])]
                matched_any = False
                near_miss_tagged = 0
                for face in copy._iter_faces():
                    if any(face.wrapped.IsSame(w) for w in matched_wrapped):
                        face._apply_tag(_MATCHED_TAG, propagate=False)
                        matched_any = True
                    elif near_miss_tagged < 3 and any(
                        face.wrapped.IsSame(w) for w in near_wrapped
                    ):
                        face._apply_tag(_NEAR_MISS_TAG, propagate=False)
                        near_miss_tagged += 1
                if matched_any:
                    highlight_tags = [_MATCHED_TAG]
                    if near_miss_tagged:
                        highlight_tags.append(_NEAR_MISS_TAG)
                    tag_labels = {
                        _MATCHED_TAG: f"matched {target_kind}(s)",
                        _NEAR_MISS_TAG: "near miss",
                    }
                    shapes = [copy]
        highlight_edges = []
        if not shapes:
            # Non-face targets: the matched entities themselves highlight as
            # orange lines.
            highlight_edges = [item.wrapped for item in items[:8]]
            if scope.__class__.__name__ == "Solid":
                shapes = [scope]
            if not shapes and not highlight_edges:
                return []

        rendered = render_failure_evidence(
            shapes,
            operation=f"ql_{target_kind}_resolve",
            caption=(
                "orange = matched, purple = near miss; "
                "see inventory for identities"
                if target_kind == "face"
                else "orange lines = matched entities; see inventory"
            ),
            dedup_key=dedup_key,
            highlight_tags=highlight_tags,
            tag_labels=tag_labels,
            highlight_edges=highlight_edges,
        )
        return [rendered] if rendered is not None else []
    except Exception:
        return []


def _resolve_scope_items(scope: Any, target_kind: str) -> List[Any]:
    if scope.__class__.__name__.lower() == target_kind:
        return [scope]
    if target_kind == "edge":
        if hasattr(scope, "get_edges"):
            return list(scope._iter_edges())
    if target_kind == "face":
        if hasattr(scope, "get_faces"):
            return list(scope._iter_faces())
    if target_kind == "shell":
        if hasattr(scope, "get_children"):
            shells = [
                child
                for child in scope.get_children()
                if child.__class__.__name__ == "Shell"
            ]
            if shells:
                return shells
        if scope.__class__.__name__ == "Shell":
            return [scope]

    if target_kind == "solid":
        if hasattr(scope, "get_solids"):
            return list(scope._iter_solids())
        if scope.__class__.__name__ == "Solid":
            return [scope]
    if target_kind == "wire":
        if hasattr(scope, "get_children"):
            return [
                child
                for child in scope.get_children()
                if child.__class__.__name__ == "Wire"
            ]
    if target_kind == "vertex":
        if hasattr(scope, "get_children"):
            return [
                child
                for child in scope.get_children()
                if child.__class__.__name__ == "Vertex"
            ]
    if isinstance(scope, Iterable) and not isinstance(scope, (str, bytes, dict)):
        return list(scope)
    raise TypeError(f"cannot resolve QL selector scope for target_kind={target_kind}")


def tag(
    pattern: str, scope: str | TagScope = TagScope.EFFECTIVE
) -> SerializablePredicate:
    """Build a tag predicate for QL filtering.

    Args:
        pattern: Exact tag string or a trailing `*` prefix match.
        scope: One of ``local``, ``inherited``, ``effective``, or ``lineage``.

    Returns:
        Serializable predicate that can be used in `Query.where(...)`.
    """

    if not isinstance(pattern, str):
        raise TypeError("pattern must be a string")
    pattern = pattern.strip()
    if not pattern:
        raise ValueError("pattern must be non-empty")
    if "*" in pattern and not pattern.endswith("*"):
        raise ValueError("only trailing '*' wildcard is supported")
    resolved_scope = normalize_tag_scope(scope)
    return SerializablePredicate(
        "tag", {"pattern": pattern, "scope": resolved_scope.value}
    )


def meta(path: str, op: str, value_: Any) -> SerializablePredicate:
    """Build a metadata comparison predicate for QL filtering.

    Args:
        path: Dot-separated metadata path.
        op: Comparison operator such as `==`, `!=`, `>`, `>=`, `<`, or `<=`.
        value_: Comparison value.

    Returns:
        Serializable predicate that compares metadata values.
    """

    if not isinstance(op, str):
        raise TypeError("op must be a string")
    return SerializablePredicate(
        "meta", {"path": path, "op": op.strip(), "value": value_}
    )


def value(path: str, default: Any = None) -> SerializableKey:
    """Build a value key extractor for ordering and projection in QL.

    Args:
        path: Property or metadata path to resolve.
        default: Fallback value when the path is missing.

    Returns:
        Serializable key function for `Query.order_by(...)`.
    """

    return SerializableKey("value", {"path": path, "default": default})


def key(path: str, default: Any = None) -> SerializableKey:
    return SerializableKey("property", {"path": path, "default": default})


def geo(field: str, default: Any = None) -> SerializableKey:
    """Shortcut for reading `geom.*` fields inside QL queries."""

    return value(f"geo.{field}", default)


def center_axis(axis: str) -> SerializableKey:
    axis = axis.lower().strip()
    if axis not in {"x", "y", "z"}:
        raise ValueError("axis must be one of 'x', 'y', 'z'")
    return key(f"geom.center.{axis}")


def prop(path: str, op: str, value_: Any) -> SerializablePredicate:
    if not isinstance(op, str):
        raise TypeError("op must be a string")
    return SerializablePredicate(
        "property_compare", {"path": path, "op": op.strip(), "value": value_}
    )


def curve_type(kind: str) -> SerializablePredicate:
    return prop("geom.type", "==", kind.upper())


def surface_type(kind: str) -> SerializablePredicate:
    return prop("geom.type", "==", kind.upper())


# Combining serializable predicates gives a serializable predicate, which is
# what ``ShapeSelector.where`` takes; the overloads let type checkers see that.
@overload
def and_(*predicates: SerializablePredicate) -> SerializablePredicate: ...
@overload
def and_(*predicates: Predicate) -> Predicate: ...
def and_(*predicates: Predicate) -> Predicate:
    """Combine predicates so all of them must match."""

    if all(isinstance(pred, SerializablePredicate) for pred in predicates):
        return SerializablePredicate(
            "and",
            children=cast(Tuple[SerializablePredicate, ...], tuple(predicates)),
        )

    def _predicate(obj: Any) -> bool:
        return all(pred(obj) for pred in predicates)

    return _predicate


@overload
def or_(*predicates: SerializablePredicate) -> SerializablePredicate: ...
@overload
def or_(*predicates: Predicate) -> Predicate: ...
def or_(*predicates: Predicate) -> Predicate:
    """Combine predicates so at least one of them must match."""

    if all(isinstance(pred, SerializablePredicate) for pred in predicates):
        return SerializablePredicate(
            "or",
            children=cast(Tuple[SerializablePredicate, ...], tuple(predicates)),
        )

    def _predicate(obj: Any) -> bool:
        return any(pred(obj) for pred in predicates)

    return _predicate


@overload
def not_(predicate: SerializablePredicate) -> SerializablePredicate: ...
@overload
def not_(predicate: Predicate) -> Predicate: ...
def not_(predicate: Predicate) -> Predicate:
    """Negate a QL predicate."""

    if isinstance(predicate, SerializablePredicate):
        return SerializablePredicate("not", children=(predicate,))

    def _predicate(obj: Any) -> bool:
        return not predicate(obj)

    return _predicate


def operation_event(op_name: str, event: str = "*") -> SerializablePredicate:
    """Match typed operation and topology-event metadata under ``track``."""

    if not isinstance(op_name, str) or not op_name.strip():
        raise ValueError("op_name must be a non-empty string")
    if not isinstance(event, str) or not event.strip():
        raise ValueError("event must be a non-empty string")
    return SerializablePredicate(
        "operation_event",
        {
            "op": op_name.strip(),
            "event": event.strip(),
        },
    )


def origin_role(role_name: str) -> SerializablePredicate:
    """Match a typed source role under ``track`` metadata."""

    if not isinstance(role_name, str) or not role_name.strip():
        raise ValueError("role_name must be a non-empty string")
    return SerializablePredicate("origin_role", {"role": role_name.strip()})


def output_role(role_name: str) -> SerializablePredicate:
    """Match a kernel-proven operation output role under ``track`` metadata."""

    if not isinstance(role_name, str) or not role_name.strip():
        raise ValueError("role_name must be a non-empty string")
    return SerializablePredicate(
        "output_role", {"role": role_name.strip().lower()}
    )


def source_binding(binding_id: str) -> SerializablePredicate:
    """Match a projected local binding by its exact source binding identity."""

    if not isinstance(binding_id, str) or not binding_id.strip():
        raise ValueError("binding_id must be a non-empty string")
    return SerializablePredicate(
        "source_binding", {"source_binding_id": binding_id.strip()}
    )


def source_topology(topo_id: str) -> SerializablePredicate:
    """Match a projected local binding by its exact source topology identity."""

    if not isinstance(topo_id, str) or not topo_id.strip():
        raise ValueError("topo_id must be a non-empty string")
    return SerializablePredicate(
        "source_topology", {"source_topo_id": topo_id.strip()}
    )


def op(op_name: str, event: str = "*") -> SerializablePredicate:
    return operation_event(op_name, event)


def origin(role_name: str) -> SerializablePredicate:
    return origin_role(role_name)


def role(role_name: str) -> SerializablePredicate:
    return tag(f"role.{role_name}.*")


class Query:
    def __init__(self, items: Iterable[Any]):
        self._items = list(items)

    def where(self, predicate: Predicate) -> "Query":
        return Query([item for item in self._items if predicate(item)])

    def order_by(self, key: KeyFn, desc: bool = False) -> "Query":
        def _safe_key(obj: Any):
            value_ = key(obj)
            return (value_ is None, value_)

        return Query(sorted(self._items, key=_safe_key, reverse=desc))

    def limit(self, count: int) -> "Query":
        if count <= 0:
            return Query([])
        return Query(self._items[:count])

    def first(self) -> Optional[Any]:
        return self._items[0] if self._items else None

    def all(self) -> List[Any]:
        return list(self._items)


def select(items: Iterable[Any]) -> Query:
    """Start a QL query over a shape collection or selector scope."""

    return Query(items)


def edges() -> ShapeSelector:
    return ShapeSelector(target_kind="edge")


def faces() -> ShapeSelector:
    return ShapeSelector(target_kind="face")


def wires() -> ShapeSelector:
    return ShapeSelector(target_kind="wire")


def vertices() -> ShapeSelector:
    return ShapeSelector(target_kind="vertex")


def solids() -> ShapeSelector:
    return ShapeSelector(target_kind="solid")


def shells() -> ShapeSelector:
    """Select Shell entities from a Shell or compatible topology scope."""
    return ShapeSelector(target_kind="shell")


def selector_from_dict(data: Dict[str, Any]) -> ShapeSelector:
    return ShapeSelector.from_dict(data)
