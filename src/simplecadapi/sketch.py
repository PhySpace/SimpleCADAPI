"""Declarative constrained sketch objects for SimpleCADAPI.

Sketches are intent-level 2D documents. Use sketch APIs to build sketch
profiles; use concrete edge/wire APIs only for paths or pure geometry.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union, cast

import numpy as np

from .core import Edge, Face, TaggedMixin, TopoMixein, Wire
from .params.expr import ScalarLike, evaluate_scalar


_POINT_EPS = 1e-9


def _fresh_id(prefix: str, existing: Mapping[str, Any]) -> str:
    index = 0
    while True:
        candidate = f"{prefix}_{index}"
        if candidate not in existing:
            return candidate
        index += 1


def _as_float(value: ScalarLike) -> float:
    return float(evaluate_scalar(value))


def _angle_delta(value: float) -> float:
    while value <= -math.pi:
        value += 2.0 * math.pi
    while value > math.pi:
        value -= 2.0 * math.pi
    return value


@dataclass(frozen=True)
class SketchEntity:
    """Serializable entity inside a declarative sketch."""

    entity_id: str
    kind: str
    data: Dict[str, Any] = field(default_factory=dict)
    construction: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "id": self.entity_id,
            "kind": self.kind,
            "construction": self.construction,
        }
        payload.update(self.data)
        return payload


@dataclass(frozen=True)
class SketchConstraint:
    """Serializable constraint inside a declarative sketch."""

    constraint_id: str
    kind: str
    targets: Tuple[Dict[str, Any], ...]
    value: Any = None
    driving: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.constraint_id,
            "kind": self.kind,
            "targets": [dict(target) for target in self.targets],
            "driving": bool(self.driving),
        }
        if self.value is not None:
            payload["value"] = self.value
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class SketchConstraintDiagnostic:
    """Diagnostic emitted by the sketch solver."""

    constraint_id: Optional[str]
    severity: str
    code: str
    message: str
    residual: Optional[float] = None


class SketchRef(TaggedMixin):
    """Stable reference to a sketch entity or subentity."""

    def __init__(
        self,
        sketch_id: str,
        entity_id: str,
        *,
        kind: str,
        subentity: str = "geometry",
    ) -> None:
        super().__init__()
        self.sketch_id = str(sketch_id)
        self.entity_id = str(entity_id)
        self.kind = str(kind)
        self.subentity = str(subentity)

    def to_dict(self) -> Dict[str, str]:
        return {
            "sketch_id": self.sketch_id,
            "entity_id": self.entity_id,
            "kind": self.kind,
            "subentity": self.subentity,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SketchRef":
        return cls(
            str(data["sketch_id"]),
            str(data["entity_id"]),
            kind=str(data["kind"]),
            subentity=str(data.get("subentity", "geometry")),
        )

    def __repr__(self) -> str:
        return (
            "SketchRef("
            f"sketch_id={self.sketch_id!r}, entity_id={self.entity_id!r}, "
            f"kind={self.kind!r}, subentity={self.subentity!r})"
        )


@dataclass
class SketchSolveResult(TaggedMixin):
    """Backend-neutral result of solving a declarative sketch."""

    sketch_id: str
    status: str
    dof: int
    residual_norm: float
    iterations: int
    solved_points: Dict[str, Tuple[float, float]]
    solved_scalars: Dict[str, float]
    solved_entities: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    diagnostics: Tuple[SketchConstraintDiagnostic, ...] = ()
    backend: str = "unknown"
    backend_version: str = "unknown"
    backend_status_code: Optional[int] = None

    def __post_init__(self) -> None:
        TaggedMixin.__init__(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sketch_id": self.sketch_id,
            "status": self.status,
            "dof": int(self.dof),
            "residual_norm": float(self.residual_norm),
            "iterations": int(self.iterations),
            "solved_points": {
                key: [float(value[0]), float(value[1])]
                for key, value in self.solved_points.items()
            },
            "solved_scalars": dict(self.solved_scalars),
            "solved_entities": self._serialize_solved_entities(),
            "diagnostics": [diag.__dict__.copy() for diag in self.diagnostics],
            "backend": self.backend,
            "backend_version": self.backend_version,
            "backend_status_code": self.backend_status_code,
        }
    def _serialize_solved_entities(self) -> Dict[str, Any]:
        def serialize(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {str(key): serialize(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [serialize(item) for item in value]
            if isinstance(value, float):
                return float(value)
            return value

        return cast(Dict[str, Any], serialize(self.solved_entities))


class Sketch(TaggedMixin, TopoMixein):
    """Declarative constrained sketch container.

    Use `make_sketch_rsketch(...)`, `add_point_rsketch(...)`,
    `add_line_rsketch(...)`, `add_circle_rsketch(...)`, and
    `constrain_*_rsketch(...)` as the canonical API for building sketch
    profiles. Public sketch construction APIs are functional and return an
    updated `Sketch` document. The legacy `curves` constructor remains only for
    reading already-built wire/edge containers.
    """

    def __init__(
        self,
        curves: Iterable[Edge | Wire] | None = None,
        *,
        name: Optional[str] = None,
        plane: Any = "XY",
        sketch_id: Optional[str] = None,
    ) -> None:
        TaggedMixin.__init__(self)
        TopoMixein.__init__(self, level=2, self_shape_ref=self)
        self.sketch_id = str(sketch_id or f"sketch_{uuid.uuid4().hex[:8]}")
        self.name = name
        self.plane = plane
        self._plane_frame()
        self.entities: Dict[str, SketchEntity] = {}
        self.entity_order: List[str] = []
        self.constraints: List[SketchConstraint] = []
        self._last_solve_result: Optional[SketchSolveResult] = None
        if curves is not None:
            for curve in curves:
                self.add_curve(curve)

    def add_curve(self, curve: Edge | Wire) -> "Sketch":
        if not isinstance(curve, (Edge, Wire)):
            raise ValueError("Sketch only supports Edge or Wire curve inputs")
        self.add_child(curve)
        return self

    def curves(self) -> List[Edge | Wire]:
        return list(self.get_children())

    def closed_wires(self) -> List[Wire]:
        result: List[Wire] = []
        for curve in self.curves():
            if isinstance(curve, Wire) and curve.is_closed():
                result.append(curve)
        return result

    def to_faces(self) -> List[Face]:
        if self.entities:
            return [self.to_face()]
        from .operators.geometry import make_face_from_wire_rface

        return [make_face_from_wire_rface(wire) for wire in self.closed_wires()]

    def to_face(
        self,
        profile: int | str = 0,
        *,
        inner_profiles: Sequence[int | str] = (),
    ) -> Face:
        from .operators.sketch import make_face_from_sketch_rface

        return make_face_from_sketch_rface(
            self,
            profile=profile,
            inner_profiles=inner_profiles,
        )

    def clone(self, *, include_solve: bool = True) -> "Sketch":
        cloned = Sketch(name=self.name, plane=self.plane, sketch_id=self.sketch_id)
        cloned._copy_tag_state_from(self)
        cloned._metadata = self._metadata.copy()
        cloned.entities = dict(self.entities)
        cloned.entity_order = list(self.entity_order)
        cloned.constraints = list(self.constraints)
        cloned._last_solve_result = self._last_solve_result if include_solve else None
        for curve in self.curves():
            cloned.add_curve(curve)
        return cloned

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sketch_id": self.sketch_id,
            "name": self.name,
            "plane": self.plane,
            "entities": [self.entities[key].to_dict() for key in self.entity_order],
            "constraints": [constraint.to_dict() for constraint in self.constraints],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Sketch":
        sketch = cls(
            name=data.get("name"),
            plane=data.get("plane", "XY"),
            sketch_id=str(data.get("sketch_id") or data.get("name") or "sketch"),
        )
        for entity_data in data.get("entities", []):
            entity_id = str(entity_data["id"])
            kind = str(entity_data["kind"])
            construction = bool(entity_data.get("construction", False))
            payload = dict(entity_data)
            payload.pop("id", None)
            payload.pop("kind", None)
            payload.pop("construction", None)
            sketch._add_entity(
                SketchEntity(entity_id, kind, payload, construction=construction)
            )
        for constraint_data in data.get("constraints", []):
            sketch.constraints.append(
                SketchConstraint(
                    constraint_id=str(constraint_data["id"]),
                    kind=str(constraint_data["kind"]),
                    targets=tuple(dict(target) for target in constraint_data.get("targets", [])),
                    value=constraint_data.get("value"),
                    driving=bool(constraint_data.get("driving", True)),
                    metadata=dict(constraint_data.get("metadata", {})),
                )
            )
        return sketch

    def ref(self, entity_id: str, *, kind: Optional[str] = None, subentity: str = "geometry") -> SketchRef:
        if entity_id not in self.entities:
            raise ValueError(f"Unknown sketch entity '{entity_id}'")
        entity = self.entities[entity_id]
        return SketchRef(self.sketch_id, entity_id, kind=kind or entity.kind, subentity=subentity)

    def point_ref(self, path: str) -> SketchRef:
        if "." in path:
            entity_id, subentity = path.split(".", 1)
            if entity_id not in self.entities:
                raise ValueError(f"Unknown sketch entity '{entity_id}'")
            entity = self.entities[entity_id]
            valid_subentities = {
                "line": {"start", "end"},
                "circle": {"center"},
                "arc": {"start", "end", "center"},
                "bspline": {"start", "end"},
                "ellipse": {"center", "major", "minor"},
            }.get(entity.kind, set())
            if subentity not in valid_subentities:
                raise ValueError(
                    f"Sketch entity '{entity_id}' has no point subentity '{subentity}'"
                )
            return SketchRef(self.sketch_id, entity_id, kind="point", subentity=subentity)
        if path not in self.entities:
            raise ValueError(f"Unknown sketch point '{path}'")
        entity = self.entities[path]
        if entity.kind != "point":
            raise ValueError(f"Sketch entity '{path}' is kind '{entity.kind}', not 'point'")
        return SketchRef(self.sketch_id, path, kind="point")

    def resolve_target(
        self,
        target: Union[SketchRef, str],
        *,
        expected: Optional[Union[str, Sequence[str]]] = None,
    ) -> SketchRef:
        if isinstance(expected, str):
            expected_kinds = {expected}
        elif expected is None:
            expected_kinds = set()
        else:
            expected_kinds = {str(item) for item in expected}

        if isinstance(target, SketchRef):
            ref = target
        elif isinstance(target, str):
            if "." in target or expected_kinds == {"point"}:
                ref = self.point_ref(target)
            else:
                if target not in self.entities:
                    raise ValueError(f"Unknown sketch entity '{target}'")
                entity = self.entities[target]
                ref = self.point_ref(target) if entity.kind == "point" else self.ref(target)
        else:
            raise TypeError("Sketch targets must be SketchRef or string ids")

        self.validate_ref(ref)
        if expected_kinds and ref.kind not in expected_kinds:
            expected_label = ", ".join(sorted(expected_kinds))
            raise ValueError(
                f"Sketch target '{ref.entity_id}' is kind '{ref.kind}', expected {expected_label}"
            )
        return ref

    def add_point(self, point_id: str, x: ScalarLike, y: ScalarLike) -> SketchRef:
        self._add_entity(SketchEntity(point_id, "point", {"x": x, "y": y}))
        return self.point_ref(point_id)

    def add_line(
        self,
        entity_id: str,
        start: SketchRef,
        end: SketchRef,
        *,
        construction: bool = False,
    ) -> "Sketch":
        start_id = self.resolve_point_id(start)
        end_id = self.resolve_point_id(end)
        if start_id == end_id:
            raise ValueError("A sketch line requires two distinct point refs")
        self._add_entity(
            SketchEntity(
                entity_id,
                "line",
                {"start": start_id, "end": end_id},
                construction=construction,
            )
        )
        return self

    def add_circle(
        self,
        entity_id: str,
        center: SketchRef,
        radius: ScalarLike,
        *,
        construction: bool = False,
    ) -> "Sketch":
        center_id = self.resolve_point_id(center)
        if _as_float(radius) <= 0.0:
            raise ValueError("A sketch circle radius must be positive")
        self._add_entity(
            SketchEntity(
                entity_id,
                "circle",
                {"center": center_id, "radius": radius},
                construction=construction,
            )
        )
        return self

    def add_arc(
        self,
        entity_id: str,
        start: SketchRef,
        end: SketchRef,
        center: SketchRef,
        *,
        construction: bool = False,
    ) -> "Sketch":
        """Add an arc edge defined by start point, end point, and center point."""
        start_id = self.resolve_point_id(start)
        end_id = self.resolve_point_id(end)
        center_id = self.resolve_point_id(center)
        if start_id == end_id:
            raise ValueError("A sketch arc requires two distinct endpoint refs")
        self._add_entity(
            SketchEntity(
                entity_id,
                "arc",
                {"start": start_id, "end": end_id, "center": center_id},
                construction=construction,
            )
        )
        return self

    def add_ellipse(
        self,
        entity_id: str,
        center: SketchRef,
        major_point: SketchRef,
        minor_point: SketchRef,
        *,
        construction: bool = False,
    ) -> "Sketch":
        """Add an ellipse derived from three solving points.

        The center point and the two axis-end points are ordinary sketch
        points; the ellipse shape is a pure function of them (major axis
        toward ``major_point``, minor radius is the distance to
        ``minor_point``), so radius constraints solve natively.
        """
        center_id = self.resolve_point_id(center)
        major_id = self.resolve_point_id(major_point)
        minor_id = self.resolve_point_id(minor_point)
        if len({center_id, major_id, minor_id}) != 3:
            raise ValueError(
                "A sketch ellipse requires three distinct axis points"
            )
        center_xy = self._entity_xy(center_id)
        major_xy = self._entity_xy(major_id)
        minor_xy = self._entity_xy(minor_id)
        major_radius = math.dist(center_xy, major_xy)
        minor_radius = math.dist(center_xy, minor_xy)
        if major_radius <= _POINT_EPS or minor_radius <= _POINT_EPS:
            raise ValueError("A sketch ellipse requires non-degenerate axes")
        if minor_radius > major_radius:
            raise ValueError(
                "A sketch ellipse requires the minor axis not to exceed the major axis"
            )
        self._add_entity(
            SketchEntity(
                entity_id,
                "ellipse",
                {
                    "center": center_id,
                    "major": major_id,
                    "minor": minor_id,
                },
                construction=construction,
            )
        )
        return self

    def _entity_xy(self, point_id: str) -> Tuple[float, float]:
        entity = self.entities[point_id]
        if entity.kind != "point":
            raise ValueError(f"Sketch entity '{point_id}' is not a point")
        return (_as_float(entity.data["x"]), _as_float(entity.data["y"]))

    def add_bspline(
        self,
        entity_id: str,
        start: SketchRef,
        end: SketchRef,
        control_points: Sequence[Any],
        degree: int = 3,
        knots: Optional[Sequence[float]] = None,
        multiplicities: Optional[Sequence[int]] = None,
        weights: Optional[Sequence[float]] = None,
        periodic: bool = False,
        *,
        construction: bool = False,
    ) -> "Sketch":
        """Add a B-spline whose poles participate in sketch solving.

        Control points may be literal 2-D coordinates or refs to points in
        this sketch. For nonperiodic curves the first and last poles share
        the declared start/end point entities. A closed curve may use one
        seam point for both endpoints; a periodic seam does not replace its
        control poles, which generally lie away from the seam.
        """
        from .operators.geometry import (
            _normalize_bspline_knots,
            _normalize_bspline_weights,
        )

        start_id = self.resolve_point_id(start)
        end_id = self.resolve_point_id(end)
        if isinstance(degree, bool) or int(degree) != degree:
            raise ValueError("degree must be an integer")
        degree_value = int(degree)
        if degree_value < 1 or degree_value > 25:
            raise ValueError("degree must be between 1 and 25")
        if len(control_points) < degree_value + 1:
            raise ValueError(
                f"bspline requires at least degree+1 control points, got {len(control_points)}"
            )
        normalized_cps: List[Any] = []
        for index, point in enumerate(control_points):
            if isinstance(point, (SketchRef, str)):
                point_ref = self.resolve_target(point, expected="point")
                normalized_cps.append(
                    {"point_id": self.resolve_point_id(point_ref)}
                )
                continue
            if isinstance(point, Mapping):
                point_id = point.get("point_id", point.get("point"))
                if point_id is None:
                    raise ValueError(
                        f"bspline control point {index} mapping requires point_id"
                    )
                point_ref = self.resolve_target(str(point_id), expected="point")
                normalized_cps.append(
                    {"point_id": self.resolve_point_id(point_ref)}
                )
                continue
            if not isinstance(point, Sequence) or isinstance(point, (str, bytes)):
                raise ValueError(
                    f"bspline control point {index} must be a 2-D coordinate or sketch point ref"
                )
            if len(point) != 2:
                raise ValueError(
                    f"bspline control point {index} must contain exactly two coordinates"
                )
            normalized_cps.append([float(point[0]), float(point[1])])

        def resolved_control_point(point: Any) -> List[float]:
            if isinstance(point, Mapping):
                point_entity = self.entities[str(point["point_id"])]
                return [
                    _as_float(point_entity.data["x"]),
                    _as_float(point_entity.data["y"]),
                ]
            return [float(point[0]), float(point[1])]

        resolved_cps = [resolved_control_point(point) for point in normalized_cps]
        resolved_knots, resolved_multiplicities = _normalize_bspline_knots(
            control_count=len(normalized_cps),
            degree=degree_value,
            periodic=bool(periodic),
            knots=knots,
            multiplicities=multiplicities,
        )
        resolved_weights = _normalize_bspline_weights(weights, len(normalized_cps))
        start_entity = self.entities[start_id]
        end_entity = self.entities[end_id]
        start_point = [_as_float(start_entity.data["x"]), _as_float(start_entity.data["y"])]
        end_point = [_as_float(end_entity.data["x"]), _as_float(end_entity.data["y"])]
        if not periodic and isinstance(normalized_cps[0], Mapping):
            if normalized_cps[0]["point_id"] != start_id:
                raise ValueError("The first B-spline control-point ref must match start")
        elif not periodic:
            normalized_cps[0] = start_point
        if not periodic and isinstance(normalized_cps[-1], Mapping):
            if normalized_cps[-1]["point_id"] != end_id:
                raise ValueError("The last B-spline control-point ref must match end")
        elif not periodic:
            normalized_cps[-1] = end_point
        if not periodic:
            resolved_cps[0] = start_point
            resolved_cps[-1] = end_point
        self._add_entity(
            SketchEntity(
                entity_id,
                "bspline",
                {
                    "start": start_id,
                    "end": end_id,
                    "control_points": normalized_cps,
                    "degree": degree_value,
                    "knots": list(resolved_knots),
                    "multiplicities": list(resolved_multiplicities),
                    "weights": list(resolved_weights) if resolved_weights is not None else None,
                    "periodic": bool(periodic),
                },
                construction=construction,
            )
        )
        return self

    def add_constraint(
        self,
        kind: str,
        targets: Sequence[SketchRef],
        *,
        value: Any = None,
        constraint_id: Optional[str] = None,
        driving: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "Sketch":
        for target in targets:
            self.validate_ref(target)
        existing = {constraint.constraint_id: constraint for constraint in self.constraints}
        cid = constraint_id or _fresh_id(f"c_{kind}", existing)
        if cid in existing:
            raise ValueError(f"Duplicate sketch constraint id '{cid}'")
        self.constraints.append(
            SketchConstraint(
                constraint_id=cid,
                kind=str(kind),
                targets=tuple(target.to_dict() for target in targets),
                value=value,
                driving=driving,
                metadata=dict(metadata or {}),
            )
        )
        return self

    def solve(
        self,
        *,
        require_fully_constrained: bool = False,
        strict: bool = True,
        tolerance: float = 1e-7,
        max_iterations: int = 80,
        backend: Any = None,
    ) -> SketchSolveResult:
        from .sketch_solver import (
            SketchSolverOptions,
            get_default_sketch_solver_backend,
            get_sketch_solver_backend,
        )

        selected_backend = (
            get_default_sketch_solver_backend()
            if backend is None
            else get_sketch_solver_backend(backend)
            if isinstance(backend, str)
            else backend
        )
        result = selected_backend.solve(
            self,
            options=SketchSolverOptions(
                tolerance=float(tolerance),
                max_iterations=int(max_iterations),
            ),
        )
        self._last_solve_result = result
        if strict and result.status in {"conflicting", "failed"}:
            # The backend already pinpointed the failing constraints; the
            # structured diagnosis (measurements/inventory/repair/2D evidence
            # render) replaces the legacy one-line ValueError.  SimpleCADError
            # subclasses ValueError, so legacy except clauses keep working.
            from .sketch_diagnostics import raise_sketch_solve_failure

            raise_sketch_solve_failure(self, result)
        if require_fully_constrained and result.dof > 0:
            from .sketch_diagnostics import raise_sketch_underconstrained

            raise_sketch_underconstrained(self, result)
        return result

    def solved_result(self) -> SketchSolveResult:
        if self._last_solve_result is None:
            return self.solve(strict=True)
        return self._last_solve_result

    def make_wire(
        self,
        profile: int | str = 0,
        *,
        solve_result: Optional[SketchSolveResult] = None,
    ) -> Wire:
        profile_payload = self._profile_payload(profile, solve_result=solve_result)
        return self._wire_from_profile_payload(profile_payload)

    def _wire_from_profile_payload(self, profile_payload: Mapping[str, Any]) -> Wire:
        from .operators.geometry import (
            make_circle_redge,
            make_line_redge,
            make_wire_from_edges_rwire,
        )

        if profile_payload["kind"] == "circle":
            center = profile_payload["center"]
            edge = make_circle_redge(center, profile_payload["radius"], profile_payload["normal"])
            wire = make_wire_from_edges_rwire([edge])
            wire._set_runtime(
                "sketch.entity_edges",
                [(str(profile_payload["entity_ids"][0]), wire.get_edges(0).wrapped)],
            )
            return wire
        if profile_payload["kind"] == "ellipse":
            from .operators.geometry import make_ellipse_redge

            edge = make_ellipse_redge(
                profile_payload["center"],
                profile_payload["major_radius"],
                profile_payload["minor_radius"],
                profile_payload["normal"],
                major_direction=profile_payload["major_direction"],
            )
            wire = make_wire_from_edges_rwire([edge])
            wire._set_runtime(
                "sketch.entity_edges",
                [(str(profile_payload["entity_ids"][0]), wire.get_edges(0).wrapped)],
            )
            return wire
        if profile_payload["kind"] == "line_loop":
            points = profile_payload["points"]
            edges = [
                make_line_redge(points[index], points[(index + 1) % len(points)])
                for index in range(len(points))
            ]
            wire = make_wire_from_edges_rwire(edges)
            wire._set_runtime(
                "sketch.entity_edges",
                list(
                    zip(
                        profile_payload["entity_ids"],
                        [edge.wrapped for edge in wire._iter_edges()],
                    )
                ),
            )
            return wire
        if profile_payload["kind"] in ("edge_loop", "edge_chain"):
            return self._wire_from_edge_entities(profile_payload)
        raise ValueError(f"Unsupported sketch profile kind '{profile_payload['kind']}'")

    def _wire_from_edge_entities(self, profile_payload: Mapping[str, Any]) -> Wire:
        """Build a wire from an ordered loop or open chain of solved entities."""
        from OCP.TopoDS import TopoDS

        from .operators.geometry import (
            make_line_redge,
            make_spline_redge,
            make_three_point_arc_redge,
            make_wire_from_edges_rwire,
        )

        entity_ids = profile_payload["entity_ids"]
        reversed_edges = profile_payload.get("reversed", [False] * len(entity_ids))
        result: SketchSolveResult = profile_payload["solve_result"]
        point_map_2d = result.solved_points
        point_map: Dict[str, Tuple[float, float, float]] = {}
        for pid, pt in result.solved_points.items():
            point_map[pid] = self._point3(pt)

        edges: List[Edge] = []
        entity_edges: List[Tuple[str, Any]] = []
        for eid, reverse_edge in zip(entity_ids, reversed_edges):
            entity = self.entities[eid]
            if entity.kind == "line":
                start_id, end_id = str(entity.data["start"]), str(entity.data["end"])
                edge = make_line_redge(point_map[start_id], point_map[end_id])
            elif entity.kind == "arc":
                start_id = str(entity.data["start"])
                end_id = str(entity.data["end"])
                center_id = str(entity.data["center"])
                sp = point_map_2d[start_id]
                ep = point_map_2d[end_id]
                cp = point_map_2d[center_id]
                start_radius = math.hypot(sp[0] - cp[0], sp[1] - cp[1])
                end_radius = math.hypot(ep[0] - cp[0], ep[1] - cp[1])
                radius_tolerance = max(_POINT_EPS, start_radius * 1.0e-7)
                if start_radius <= _POINT_EPS:
                    raise ValueError(f"Sketch arc '{eid}' has zero radius")
                if abs(start_radius - end_radius) > radius_tolerance:
                    raise ValueError(
                        f"Sketch arc '{eid}' endpoints are not equidistant from its center"
                    )
                start_angle = math.atan2(sp[1] - cp[1], sp[0] - cp[0])
                end_angle = math.atan2(ep[1] - cp[1], ep[0] - cp[0])
                sweep = (end_angle - start_angle) % (2.0 * math.pi)
                if sweep <= 1.0e-12:
                    raise ValueError(f"Sketch arc '{eid}' has a zero sweep")
                middle_angle = start_angle + 0.5 * sweep
                middle = self._point3(
                    (
                        cp[0] + start_radius * math.cos(middle_angle),
                        cp[1] + start_radius * math.sin(middle_angle),
                    )
                )
                edge = make_three_point_arc_redge(
                    point_map[start_id],
                    middle,
                    point_map[end_id],
                )
            elif entity.kind == "bspline":
                solved_poles = [
                    tuple(point)
                    for point in result.solved_entities[eid]["control_points"]
                ]
                cps_3d = [self._point3(point) for point in solved_poles]
                edge = make_spline_redge(
                    control_points=cps_3d,
                    degree=int(entity.data["degree"]),
                    knots=entity.data["knots"],
                    multiplicities=entity.data["multiplicities"],
                    weights=entity.data.get("weights"),
                    periodic=bool(entity.data.get("periodic", False)),
                )
            else:
                raise ValueError(f"Unsupported edge kind '{entity.kind}' in edge path profile")
            if reverse_edge:
                edge = Edge(TopoDS.Edge_s(edge.wrapped.Reversed()))
            edges.append(edge)
            entity_edges.append((str(eid), edge.wrapped))
        wire = make_wire_from_edges_rwire(edges)
        wire_edges = list(wire._iter_edges())
        if len(wire_edges) != len(entity_edges):
            raise ValueError(
                "Sketch profile wire edge count changed during kernel construction"
            )
        wire._set_runtime(
            "sketch.entity_edges",
            [
                (entity_id, wire_edge.wrapped)
                for (entity_id, _source_edge), wire_edge in zip(
                    entity_edges, wire_edges
                )
            ],
        )
        return wire

    def make_face(
        self,
        profile: int | str = 0,
        *,
        inner_profiles: Sequence[int | str] = (),
        solve_result: Optional[SketchSolveResult] = None,
    ) -> Face:
        from .operators.sketch import make_face_from_sketch_rface

        if solve_result is not None:
            raise ValueError(
                "Pass solve settings through make_face_from_sketch_rface; an external solve_result is not supported for multi-loop faces"
            )
        return make_face_from_sketch_rface(
            self,
            profile=profile,
            inner_profiles=inner_profiles,
        )

    def _add_entity(self, entity: SketchEntity) -> None:
        if entity.entity_id in self.entities:
            raise ValueError(f"Duplicate sketch entity id '{entity.entity_id}'")
        self.entities[entity.entity_id] = entity
        self.entity_order.append(entity.entity_id)

    def validate_ref(self, ref: SketchRef) -> None:
        if not isinstance(ref, SketchRef):
            raise TypeError("Sketch constraints require SketchRef targets")
        if ref.sketch_id != self.sketch_id:
            raise ValueError("SketchRef belongs to a different sketch")
        if ref.entity_id not in self.entities:
            raise ValueError(f"Unknown sketch entity '{ref.entity_id}'")
        if ref.kind == "point":
            self.resolve_point_id(ref)
        elif ref.kind in {"line", "circle", "arc", "bspline", "ellipse"}:
            entity = self.entities[ref.entity_id]
            if entity.kind != ref.kind:
                raise ValueError(
                    f"SketchRef '{ref.entity_id}' is kind '{entity.kind}', not '{ref.kind}'"
                )

    def resolve_point_id(self, ref: SketchRef) -> str:
        if ref.sketch_id != self.sketch_id:
            raise ValueError("SketchRef belongs to a different sketch")
        if ref.entity_id not in self.entities:
            raise ValueError(f"Unknown sketch entity '{ref.entity_id}'")
        entity = self.entities[ref.entity_id]
        if ref.kind == "point" and entity.kind == "point":
            return ref.entity_id
        if entity.kind == "line" and ref.subentity in {"start", "end"}:
            return str(entity.data[ref.subentity])
        if entity.kind == "circle" and ref.subentity == "center":
            return str(entity.data["center"])
        if entity.kind == "arc" and ref.subentity in {"start", "end", "center"}:
            return str(entity.data[ref.subentity])
        if entity.kind == "bspline" and ref.subentity in {"start", "end"}:
            return str(entity.data[ref.subentity])
        if entity.kind == "ellipse" and ref.subentity in {"center", "major", "minor"}:
            return str(entity.data[ref.subentity])
        raise ValueError(f"Cannot resolve {ref!r} to a sketch point")

    def _constraint_refs(self, constraint: SketchConstraint) -> List[SketchRef]:
        return [SketchRef.from_dict(target) for target in constraint.targets]

    def _plane_frame(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        plane = self.plane
        if isinstance(plane, str):
            token = plane.upper()
            if token == "XY":
                return (
                    np.array([0.0, 0.0, 0.0]),
                    np.array([1.0, 0.0, 0.0]),
                    np.array([0.0, 1.0, 0.0]),
                    np.array([0.0, 0.0, 1.0]),
                )
            if token == "XZ":
                return (
                    np.array([0.0, 0.0, 0.0]),
                    np.array([1.0, 0.0, 0.0]),
                    np.array([0.0, 0.0, 1.0]),
                    np.array([0.0, -1.0, 0.0]),
                )
            if token == "YZ":
                return (
                    np.array([0.0, 0.0, 0.0]),
                    np.array([0.0, 1.0, 0.0]),
                    np.array([0.0, 0.0, 1.0]),
                    np.array([1.0, 0.0, 0.0]),
                )
        if isinstance(plane, Mapping):
            origin = np.array(plane.get("origin", (0.0, 0.0, 0.0)), dtype=float)
            x_axis = np.array(plane.get("x_axis", (1.0, 0.0, 0.0)), dtype=float)
            y_axis = np.array(plane.get("y_axis", (0.0, 1.0, 0.0)), dtype=float)
            if origin.shape != (3,) or x_axis.shape != (3,) or y_axis.shape != (3,):
                raise ValueError("Sketch plane origin and axes must be 3-D vectors")
            if not all(np.all(np.isfinite(vector)) for vector in (origin, x_axis, y_axis)):
                raise ValueError("Sketch plane origin and axes must contain finite values")
            x_length = float(np.linalg.norm(x_axis))
            if x_length <= 1.0e-15:
                raise ValueError("Sketch plane x_axis must be non-zero")
            x_axis = x_axis / x_length
            y_axis = y_axis - float(np.dot(y_axis, x_axis)) * x_axis
            y_length = float(np.linalg.norm(y_axis))
            if y_length <= 1.0e-15:
                raise ValueError("Sketch plane x_axis and y_axis must not be parallel")
            y_axis = y_axis / y_length
            normal = np.cross(x_axis, y_axis)
            normal = normal / np.linalg.norm(normal)
            return origin, x_axis, y_axis, normal
        raise ValueError("Sketch plane must be 'XY', 'XZ', 'YZ', or a plane mapping")

    def _point3(self, point: Tuple[float, float]) -> Tuple[float, float, float]:
        origin, x_axis, y_axis, _normal = self._plane_frame()
        vec = origin + float(point[0]) * x_axis + float(point[1]) * y_axis
        return (float(vec[0]), float(vec[1]), float(vec[2]))

    def _plane_normal_tuple(self) -> Tuple[float, float, float]:
        _origin, _x_axis, _y_axis, normal = self._plane_frame()
        return (float(normal[0]), float(normal[1]), float(normal[2]))

    def _profile_payload(
        self,
        profile: int | str = 0,
        *,
        solve_result: Optional[SketchSolveResult] = None,
        require_closed: bool = False,
    ) -> Dict[str, Any]:
        result = solve_result or self.solved_result()
        profiles = self._profiles_from_solution(result)
        if require_closed:
            closed_profiles = [item for item in profiles if item.get("closed", True)]
            if not closed_profiles:
                raise ValueError(
                    "Sketch contains no closed profile; face promotion requires a "
                    "closed loop. Components: "
                    + "; ".join(self._describe_edge_components())
                )
            profiles = closed_profiles
        if not profiles:
            descriptions = self._describe_edge_components()
            detail = (
                "Components: " + "; ".join(descriptions)
                if descriptions
                else "The sketch has no non-construction edge entities."
            )
            raise ValueError(
                "Sketch contains no promotable closed loop or open chain. " + detail
            )
        if isinstance(profile, str):
            for item in profiles:
                if item.get("id") == profile:
                    return item
            raise ValueError(f"Unknown sketch profile '{profile}'")
        index = int(profile)
        if index < 0 or index >= len(profiles):
            raise ValueError(f"Sketch profile index {index} is out of range")
        return profiles[index]

    def _profiles_from_solution(self, result: SketchSolveResult) -> List[Dict[str, Any]]:
        profiles: List[Dict[str, Any]] = []
        for entity_id in self.entity_order:
            entity = self.entities[entity_id]
            if entity.construction:
                continue
            if entity.kind == "circle":
                center_id = str(entity.data["center"])
                scalar_key = f"circle:{entity_id}:radius"
                center = result.solved_points[center_id]
                profiles.append(
                    {
                        "id": entity_id,
                        "kind": "circle",
                        "closed": True,
                        "entity_ids": [entity_id],
                        "center": self._point3(center),
                        "radius": float(result.solved_scalars[scalar_key]),
                        "normal": self._plane_normal_tuple(),
                    }
                )
            if entity.kind == "ellipse":
                center = result.solved_points[str(entity.data["center"])]
                major = result.solved_points[str(entity.data["major"])]
                minor = result.solved_points[str(entity.data["minor"])]
                center3 = self._point3(center)
                major3 = self._point3(major)
                minor3 = self._point3(minor)
                profiles.append(
                    {
                        "id": entity_id,
                        "kind": "ellipse",
                        "closed": True,
                        "entity_ids": [entity_id],
                        "center": center3,
                        "major_radius": math.dist(center3, major3),
                        "minor_radius": math.dist(center3, minor3),
                        "major_direction": tuple(
                            value - ref
                            for value, ref in zip(major3, center3)
                        ),
                        "normal": self._plane_normal_tuple(),
                    }
                )
        profiles.extend(self._edge_path_profiles(result))
        return profiles

    # --- Edge kinds that participate in closed-loop profiles ---
    _EDGE_KINDS = frozenset({"line", "arc", "bspline"})

    @staticmethod
    def _edge_endpoints(entity: SketchEntity) -> Tuple[str, str]:
        """Extract (start_point_id, end_point_id) from any edge entity."""
        return str(entity.data["start"]), str(entity.data["end"])

    def _edge_path_profiles(self, result: SketchSolveResult) -> List[Dict[str, Any]]:
        edge_ids = [
            entity_id
            for entity_id in self.entity_order
            if self.entities[entity_id].kind in self._EDGE_KINDS
            and not self.entities[entity_id].construction
        ]
        unused = set(edge_ids)
        profiles: List[Dict[str, Any]] = []
        while unused:
            first_edge = min(unused, key=self.entity_order.index)
            component = self._edge_component(first_edge, unused)
            unused.difference_update(component)
            ordered = self._ordered_edge_path(component)
            if ordered is None:
                continue
            point_ids, oriented_edges, closed = ordered
            payload: Dict[str, Any] = {
                "id": component[0],
                "kind": "edge_loop" if closed else "edge_chain",
                "closed": closed,
                "entity_ids": [edge_id for edge_id, _reversed in oriented_edges],
                "reversed": [reversed_edge for _edge_id, reversed_edge in oriented_edges],
                "point_ids": list(point_ids),
                "points": [self._point3(result.solved_points[pid]) for pid in point_ids],
                "solve_result": result,
            }
            if not closed:
                payload["endpoints"] = [point_ids[0], point_ids[-1]]
            profiles.append(payload)
        return profiles

    def _edge_component(self, first_edge: str, candidates: set[str]) -> List[str]:
        queue = [first_edge]
        seen_edges: set[str] = set()
        seen_points: set[str] = set()
        while queue:
            edge_id = queue.pop(0)
            if edge_id in seen_edges:
                continue
            seen_edges.add(edge_id)
            entity = self.entities[edge_id]
            for point_id in self._edge_endpoints(entity):
                if point_id in seen_points:
                    continue
                seen_points.add(point_id)
                for other_id in candidates:
                    other = self.entities[other_id]
                    if point_id in set(self._edge_endpoints(other)):
                        queue.append(other_id)
        return sorted(seen_edges, key=self.entity_order.index)

    def _ordered_edge_path(
        self,
        edge_ids: Sequence[str],
    ) -> Optional[Tuple[List[str], List[Tuple[str, bool]], bool]]:
        """Order a connected edge component into one walkable path.

        A connected component whose vertices all have degree <= 2 is either a
        simple cycle (no degree-1 vertices) or a simple open chain (exactly
        two). Anything else — branching, or the impossible odd-endpoint
        patterns — has no ordered edge sequence and returns None. The return
        value is ``(point_ids, oriented_edges, closed)``; closedness is a
        property of the outcome, enforced by consumers that need it.
        """
        adjacency: Dict[str, List[str]] = {}
        for edge_id in edge_ids:
            entity = self.entities[edge_id]
            start, end = self._edge_endpoints(entity)
            adjacency.setdefault(start, []).append(edge_id)
            adjacency.setdefault(end, []).append(edge_id)
        if not adjacency or any(len(edges) > 2 for edges in adjacency.values()):
            return None
        endpoints = [pid for pid, edges in adjacency.items() if len(edges) == 1]
        if len(endpoints) == 2:
            closed = False
            start_point = endpoints[0]
            start_edge = adjacency[start_point][0]
        elif not endpoints:
            closed = True
            start_edge = edge_ids[0]
            start_point = self._edge_endpoints(self.entities[start_edge])[0]
        else:
            return None

        first_start, first_end = self._edge_endpoints(self.entities[start_edge])
        if first_start == start_point:
            current_point = first_end
            reversed_edge = False
        else:
            current_point = first_start
            reversed_edge = True
        used_edges = {start_edge}
        ordered_points = [start_point, current_point]
        oriented_edges = [(start_edge, reversed_edge)]

        while True:
            if closed and current_point == start_point:
                break
            options = [eid for eid in adjacency[current_point] if eid not in used_edges]
            if not options:
                if closed or len(used_edges) != len(edge_ids):
                    return None
                break
            next_edge = options[0]
            used_edges.add(next_edge)
            next_start, next_end = self._edge_endpoints(self.entities[next_edge])
            reversed_edge = next_start != current_point
            oriented_edges.append((next_edge, reversed_edge))
            current_point = next_start if reversed_edge else next_end
            if not (closed and current_point == start_point):
                ordered_points.append(current_point)
        if len(used_edges) != len(edge_ids):
            return None
        if closed and current_point != start_point:
            return None
        return ordered_points, oriented_edges, closed

    def _describe_edge_components(self) -> List[str]:
        """Classify every non-construction edge component for diagnostics."""
        edge_ids = [
            entity_id
            for entity_id in self.entity_order
            if self.entities[entity_id].kind in self._EDGE_KINDS
            and not self.entities[entity_id].construction
        ]
        unused = set(edge_ids)
        descriptions: List[str] = []
        while unused:
            first_edge = min(unused, key=self.entity_order.index)
            component = self._edge_component(first_edge, unused)
            unused.difference_update(component)
            descriptions.append(self._describe_edge_component(component))
        return descriptions

    def _describe_edge_component(self, edge_ids: Sequence[str]) -> str:
        adjacency: Dict[str, List[str]] = {}
        for edge_id in edge_ids:
            entity = self.entities[edge_id]
            start, end = self._edge_endpoints(entity)
            adjacency.setdefault(start, []).append(edge_id)
            adjacency.setdefault(end, []).append(edge_id)
        listed = "/".join(edge_ids)
        branch_points = [
            pid for pid, edges in adjacency.items() if len(edges) > 2
        ]
        if branch_points:
            return (
                f"branched edge set ({listed}) with branch point "
                f"'{branch_points[0]}' carrying {len(adjacency[branch_points[0]])} edges"
            )
        endpoints = [pid for pid, edges in adjacency.items() if len(edges) == 1]
        if len(endpoints) == 2:
            return f"open chain ({listed}) from '{endpoints[0]}' to '{endpoints[1]}'"
        if not endpoints:
            return f"closed loop ({listed})"
        return f"irregular edge set ({listed})"




__all__ = [
    "Sketch",
    "SketchRef",
    "SketchSolveResult",
    "SketchConstraint",
    "SketchConstraintDiagnostic",
]
