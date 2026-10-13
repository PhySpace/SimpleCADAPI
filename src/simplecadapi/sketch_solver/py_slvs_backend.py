"""SolveSpace ``py-slvs`` adapter for SimpleCAD sketch documents."""

from __future__ import annotations

import importlib.metadata
import math
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Sequence, Tuple
from OCP.Geom import Geom_BSplineCurve
from OCP.GeomConvert import GeomConvert_BSplineCurveToBezierCurve
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
from OCP.gp import gp_Pnt

from .backend import SketchSolverOptions

if TYPE_CHECKING:
    from ..sketch import (
        Sketch,
        SketchConstraint,
        SketchConstraintDiagnostic,
        SketchEntity,
        SketchRef,
        SketchSolveResult,
    )


_RESULT_OKAY = 0
_RESULT_INCONSISTENT = 1
_RESULT_DIDNT_CONVERGE = 2
_RESULT_TOO_MANY_UNKNOWNS = 3
_RESULT_INIT_ERROR = 4
_RESULT_REDUNDANT_OK = 5


class PySlvsSketchSolverBackend:
    """Sketch solver backend backed by the existing ``py-slvs`` package."""

    name = "py-slvs"

    @property
    def version(self) -> str:
        try:
            return importlib.metadata.version("py-slvs")
        except importlib.metadata.PackageNotFoundError:
            return "unknown"

    def solve(
        self,
        sketch: "Sketch",
        *,
        options: SketchSolverOptions,
    ) -> "SketchSolveResult":
        del options  # The libslvs C API does not expose these numerical knobs.
        adapter = _PySlvsSystem(sketch)
        return adapter.solve()


class _PySlvsSystem:
    _FIXED_GROUP = 1
    _SOLVE_GROUP = 2

    def __init__(self, sketch: "Sketch") -> None:
        try:
            from py_slvs import slvs
        except ImportError as exc:
            raise RuntimeError(
                "The default sketch solver backend requires 'py-slvs'. "
                "Install SimpleCADAPI with its declared runtime dependencies."
            ) from exc

        self.slvs = slvs
        self.sketch = sketch
        self.system = slvs.System()
        self.workplane = self.system.addWorkplane(
            self.system.addPoint3dV(0.0, 0.0, 0.0, group=self._FIXED_GROUP),
            self.system.addNormal3dV(1.0, 0.0, 0.0, 0.0, group=self._FIXED_GROUP),
            group=self._FIXED_GROUP,
        )
        self.point_handles: Dict[str, int] = {}
        self.entity_handles: Dict[str, int] = {}
        self.radius_entities: Dict[str, int] = {}
        self.bspline_pole_handles: Dict[str, List[int]] = {}
        self.bspline_segment_handles: Dict[str, List[int]] = {}
        self.bspline_solver_modes: Dict[str, str] = {}
        self.constraint_ids: Dict[int, str] = {}
        self._measurement_constraints: List["SketchConstraint"] = []

    def solve(self) -> "SketchSolveResult":
        from ..sketch import SketchConstraintDiagnostic, SketchSolveResult

        self._add_points()
        self._add_entities()
        self._add_constraints()
        result_code = int(
            self.system.solve(
                self._SOLVE_GROUP,
                reportFailed=True,
                findFreeParams=True,
            )
        )
        points = self._solved_points()
        scalars = self._solved_scalars(points)
        entities = self._solved_entities(points, scalars)
        failed_ids = self._failed_constraint_ids()
        diagnostics: List[SketchConstraintDiagnostic] = []

        if result_code in {_RESULT_OKAY, _RESULT_REDUNDANT_OK}:
            dof = max(0, int(self.system.Dof))
            status = "underconstrained" if dof > 0 else "solved"
            if result_code == _RESULT_REDUNDANT_OK:
                diagnostics.append(
                    SketchConstraintDiagnostic(
                        None,
                        "warning",
                        "redundant_constraints",
                        "Sketch has redundant but consistent constraints.",
                    )
                )
            if dof > 0:
                diagnostics.append(
                    SketchConstraintDiagnostic(
                        None,
                        "warning",
                        "underconstrained",
                        f"Sketch has {dof} remaining DOF.",
                    )
                )
        else:
            dof = max(0, int(self.system.Dof))
            status = "conflicting" if result_code == _RESULT_INCONSISTENT else "failed"
            code, message = self._failure_description(result_code)
            legacy_code = "residual_too_large" if result_code == _RESULT_INCONSISTENT else code
            if failed_ids:
                diagnostics.extend(
                    SketchConstraintDiagnostic(
                        constraint_id,
                        "error",
                        legacy_code,
                        message,
                    )
                    for constraint_id in failed_ids
                )
            else:
                diagnostics.append(
                    SketchConstraintDiagnostic(None, "error", legacy_code, message)
                )

        self._add_measurements(points, scalars)
        return SketchSolveResult(
            sketch_id=self.sketch.sketch_id,
            status=status,
            dof=dof,
            residual_norm=0.0 if result_code in {_RESULT_OKAY, _RESULT_REDUNDANT_OK} else math.inf,
            iterations=0,
            solved_points=points,
            solved_scalars=scalars,
            solved_entities=entities,
            diagnostics=tuple(diagnostics),
            backend=PySlvsSketchSolverBackend.name,
            backend_version=PySlvsSketchSolverBackend().version,
            backend_status_code=result_code,
        )

    def _add_points(self) -> None:
        from ..sketch import _as_float

        for entity_id in self.sketch.entity_order:
            entity = self.sketch.entities[entity_id]
            if entity.kind != "point":
                continue
            self.point_handles[entity_id] = self.system.addPoint2dV(
                self.workplane,
                _as_float(entity.data["x"]),
                _as_float(entity.data["y"]),
                group=self._SOLVE_GROUP,
            )

    def _add_entities(self) -> None:
        from ..sketch import _as_float

        for entity_id in self.sketch.entity_order:
            entity = self.sketch.entities[entity_id]
            if entity.kind == "point":
                self.entity_handles[entity_id] = self.point_handles[entity_id]
            elif entity.kind == "line":
                self.entity_handles[entity_id] = self.system.addLineSegment(
                    self.point_handles[str(entity.data["start"])],
                    self.point_handles[str(entity.data["end"])],
                    group=self._SOLVE_GROUP,
                )
            elif entity.kind == "circle":
                distance = self.system.addDistanceV(
                    _as_float(entity.data["radius"]),
                    group=self._SOLVE_GROUP,
                )
                self.radius_entities[entity_id] = distance
                self.entity_handles[entity_id] = self.system.addCircle(
                    self.point_handles[str(entity.data["center"])],
                    self.system.getEntity(self.workplane).normal,
                    distance,
                    group=self._SOLVE_GROUP,
                )
            elif entity.kind == "arc":
                self.entity_handles[entity_id] = self.system.addArcOfCircle(
                    self.workplane,
                    self.point_handles[str(entity.data["center"])],
                    self.point_handles[str(entity.data["start"])],
                    self.point_handles[str(entity.data["end"])],
                    group=self._SOLVE_GROUP,
                )
            elif entity.kind == "bspline":
                self._add_bspline_entity(entity_id, entity.data)
            elif entity.kind == "ellipse":
                # The ellipse is a pure function of its three axis points;
                # no solver entity is needed and radius constraints act on
                # the points directly.
                pass
            else:
                raise ValueError(f"Unsupported sketch entity kind '{entity.kind}'")

    def _add_bspline_entity(
        self,
        entity_id: str,
        data: Mapping[str, object],
    ) -> None:
        raw_points = data["control_points"]
        resolved_points = self._resolved_bspline_control_points(data)
        segments = self._bezier_segments_from_bspline(data)
        solver_mode = "cubic_bezier" if segments is not None else "fixed_shape"
        poles: List[int] = []
        for index, point in enumerate(raw_points):
            point_id = (
                str(point.get("point_id", point.get("point")))
                if isinstance(point, Mapping)
                else None
            )
            if point_id is None and index == 0 and not data.get("periodic", False):
                point_id = str(data["start"])
            elif point_id is None and index == len(raw_points) - 1 and not data.get("periodic", False):
                point_id = str(data["end"])
            if point_id is not None:
                endpoint = self.point_handles[str(point_id)]
                poles.append(
                    self.system.addPoint2d(
                        self.workplane,
                        self.system.getEntityParam(endpoint, 0),
                        self.system.getEntityParam(endpoint, 1),
                        group=self._SOLVE_GROUP,
                    )
                )
            else:
                poles.append(
                    self.system.addPoint2dV(
                        self.workplane,
                        float(resolved_points[index][0]),
                        float(resolved_points[index][1]),
                        group=self._SOLVE_GROUP if segments is not None else self._FIXED_GROUP,
                    )
                )
        self.bspline_pole_handles[entity_id] = poles
        self.bspline_solver_modes[entity_id] = solver_mode

        segment_handles: List[int] = []
        for indices in segments or ():
            handles = [poles[index] for index in indices]
            segment_handles.append(
                self.system.addCubic(
                    self.workplane,
                    handles[0],
                    handles[1],
                    handles[2],
                    handles[3],
                    group=self._SOLVE_GROUP,
                )
            )
        self.bspline_segment_handles[entity_id] = segment_handles
        if len(segment_handles) == 1:
            self.entity_handles[entity_id] = segment_handles[0]

    def _resolved_bspline_control_points(
        self,
        data: Mapping[str, object],
    ) -> List[Tuple[float, float]]:
        from ..sketch import _as_float

        points: List[Tuple[float, float]] = []
        for control in data["control_points"]:
            if isinstance(control, Mapping):
                point_id = control.get("point_id", control.get("point"))
                if point_id is None:
                    raise ValueError("B-spline control-point mapping requires point_id")
                point = self.sketch.entities[str(point_id)]
                points.append(
                    (_as_float(point.data["x"]), _as_float(point.data["y"]))
                )
            else:
                points.append((float(control[0]), float(control[1])))
        return points

    def _bezier_segments_from_bspline(
        self,
        data: Mapping[str, object],
    ) -> Optional[List[Tuple[int, int, int, int]]]:
        control_points = self._resolved_bspline_control_points(data)
        weights = data.get("weights")
        degree = int(data["degree"])
        if bool(data.get("periodic", False)):
            return None
        if weights is not None and any(abs(float(weight) - 1.0) > 1e-12 for weight in weights):
            return None

        poles = TColgp_Array1OfPnt(1, len(control_points))
        for index, point in enumerate(control_points, start=1):
            poles.SetValue(index, gp_Pnt(float(point[0]), float(point[1]), 0.0))
        knots = data["knots"]
        knot_array = TColStd_Array1OfReal(1, len(knots))
        for index, knot in enumerate(knots, start=1):
            knot_array.SetValue(index, float(knot))
        multiplicities = data["multiplicities"]
        mult_array = TColStd_Array1OfInteger(1, len(multiplicities))
        for index, multiplicity in enumerate(multiplicities, start=1):
            mult_array.SetValue(index, int(multiplicity))

        curve = Geom_BSplineCurve(
            poles,
            knot_array,
            mult_array,
            degree,
            False,
        )
        converter = GeomConvert_BSplineCurveToBezierCurve(curve)
        bezier_poles: List[Tuple[float, float]] = []
        for segment_index in range(1, converter.NbArcs() + 1):
            bezier = converter.Arc(segment_index)
            if bezier.Degree() < 3:
                bezier.Increase(3)
            if bezier.Degree() != 3:
                return None
            segment = [
                (float(bezier.Pole(index).X()), float(bezier.Pole(index).Y()))
                for index in range(1, 5)
            ]
            if segment_index == 1:
                bezier_poles.extend(segment)
            else:
                bezier_poles.extend(segment[1:])

        original = [tuple(map(float, point)) for point in control_points]
        if len(bezier_poles) != len(original) or any(
            math.dist(actual, expected) > 1e-9
            for actual, expected in zip(bezier_poles, original)
        ):
            return None
        return [
            (index, index + 1, index + 2, index + 3)
            for index in range(0, len(original) - 1, 3)
        ]

    def _add_constraints(self) -> None:
        for constraint in self.sketch.constraints:
            if not constraint.driving:
                self._measurement_constraints.append(constraint)
                continue
            handles = self._lower_constraint(constraint)
            for handle in handles:
                self.constraint_ids[int(handle)] = constraint.constraint_id

    def _lower_constraint(self, constraint: "SketchConstraint") -> Sequence[int]:
        from ..sketch import _as_float

        refs = self.sketch._constraint_refs(constraint)
        kind = constraint.kind
        if kind == "fix":
            return self._fix(refs[0])
        if kind == "coincident":
            return [self.system.addPointsCoincident(self._point(refs[0]), self._point(refs[1]), self.workplane, group=self._SOLVE_GROUP)]
        if kind == "horizontal":
            return [self.system.addLineHorizontal(self._entity(refs[0]), self.workplane, group=self._SOLVE_GROUP)]
        if kind == "vertical":
            return [self.system.addLineVertical(self._entity(refs[0]), self.workplane, group=self._SOLVE_GROUP)]
        if kind == "points_horizontal":
            return [self.system.addPointsHorizontal(self._point(refs[0]), self._point(refs[1]), self.workplane, group=self._SOLVE_GROUP)]
        if kind == "points_vertical":
            return [self.system.addPointsVertical(self._point(refs[0]), self._point(refs[1]), self.workplane, group=self._SOLVE_GROUP)]
        if kind == "normal":
            return self._normal(constraint, refs)
        if kind == "parallel":
            return [self.system.addParallel(self._entity(refs[0]), self._entity(refs[1]), self.workplane, group=self._SOLVE_GROUP)]
        if kind == "perpendicular":
            return [self.system.addPerpendicular(self._entity(refs[0]), self._entity(refs[1]), self.workplane, group=self._SOLVE_GROUP)]
        if kind == "collinear":
            a = self._entity(refs[0])
            b = self._entity(refs[1])
            return [
                self.system.addParallel(a, b, self.workplane, group=self._SOLVE_GROUP),
                self.system.addPointOnLine(self._line_endpoint(refs[0], "start"), b, self.workplane, group=self._SOLVE_GROUP),
            ]
        if kind == "equal_length":
            return [self.system.addEqualLength(self._entity(refs[0]), self._entity(refs[1]), self.workplane, group=self._SOLVE_GROUP)]
        if kind == "equal_radius":
            return [self.system.addEqualRadius(self._entity(refs[0]), self._entity(refs[1]), group=self._SOLVE_GROUP)]
        if kind == "distance":
            return [self.system.addPointsDistance(_as_float(constraint.value), self._point(refs[0]), self._point(refs[1]), self.workplane, group=self._SOLVE_GROUP)]
        if kind in {"distance_x", "distance_y"}:
            return [self._add_axis_distance(constraint, refs, kind)]
        if kind == "length":
            entity = self.sketch.entities[refs[0].entity_id]
            if entity.kind != "line":
                raise ValueError(
                    "Driving length constraints are supported only for lines; "
                    f"use driving=False to measure {entity.kind} length"
                )
            return [self.system.addPointsDistance(
                _as_float(constraint.value),
                self.point_handles[str(entity.data["start"])],
                self.point_handles[str(entity.data["end"])],
                self.workplane,
                group=self._SOLVE_GROUP,
            )]
        if kind in {"major_radius", "minor_radius"}:
            ellipse = self.sketch.entities[refs[0].entity_id]
            if ellipse.kind != "ellipse":
                raise ValueError(
                    f"'{kind}' requires an ellipse target, got '{ellipse.kind}'"
                )
            axis_key = "major" if kind == "major_radius" else "minor"
            return [self.system.addPointsDistance(
                _as_float(constraint.value),
                self.point_handles[str(ellipse.data["center"])],
                self.point_handles[str(ellipse.data[axis_key])],
                self.workplane,
                group=self._SOLVE_GROUP,
            )]
        if kind in {"radius", "diameter"}:
            diameter = _as_float(constraint.value) * (2.0 if kind == "radius" else 1.0)
            target = self.sketch.entities[refs[0].entity_id]
            if target.kind == "arc":
                return [self.system.addDiameter(diameter, self._entity(refs[0]), group=self._SOLVE_GROUP)]
            return [self.system.addDiameter(diameter, self._entity(refs[0]), group=self._SOLVE_GROUP)]
        if kind == "point_on":
            target = self.sketch.entities[refs[1].entity_id]
            if target.kind == "line":
                return [self.system.addPointOnLine(self._point(refs[0]), self._entity(refs[1]), self.workplane, group=self._SOLVE_GROUP)]
            if target.kind in {"circle", "arc"}:
                return [self.system.addPointOnCircle(self._point(refs[0]), self._entity(refs[1]), group=self._SOLVE_GROUP)]
            raise ValueError(f"Unsupported point_on target kind '{target.kind}'")
        if kind == "angle":
            # SolveSpace constrains the undirected angle between the two line
            # directions; the two directed solutions (+theta, -theta) both
            # satisfy it and the solver picks the basin nearest the initial
            # geometry. Fold the directed value into the smaller magnitude so
            # either directed branch can be held.
            value = _as_float(constraint.value)
            magnitude = value % 360.0
            if magnitude < 1e-9 or abs(magnitude - 360.0) < 1e-9:
                raise ValueError(
                    "A driving angle of 0/360 degrees means the lines are "
                    "parallel — use constrain_parallel_rsketch instead"
                )
            magnitude = min(magnitude, 360.0 - magnitude)
            return [self.system.addAngle(
                magnitude,
                False,
                self._entity(refs[0]),
                self._entity(refs[1]),
                self.workplane,
                group=self._SOLVE_GROUP,
            )]
        if kind == "concentric":
            return [self.system.addPointsCoincident(self._circle_center(refs[0]), self._circle_center(refs[1]), self.workplane, group=self._SOLVE_GROUP)]
        if kind == "midpoint":
            return [self.system.addMidPoint(self._point(refs[0]), self._entity(refs[1]), self.workplane, group=self._SOLVE_GROUP)]
        if kind == "symmetric":
            return self._symmetric_about_line(
                self._point(refs[0]),
                self._point(refs[1]),
                self._entity(refs[2]),
                self._initial_point(self.sketch.resolve_point_id(refs[0])),
                self._initial_point(self.sketch.resolve_point_id(refs[1])),
            )
        if kind == "mirror":
            return self._mirror(constraint, refs)
        if kind == "midpoint_points":
            return self._midpoint_points(refs)
        if kind == "line_distance":
            return self._line_distance(constraint, refs)
        if kind == "tangent":
            return self._tangent(constraint, refs)
        raise ValueError(f"Unsupported sketch constraint kind '{kind}'")

    def _fix(self, ref: "SketchRef") -> Sequence[int]:
        entity = self.sketch.entities[ref.entity_id]
        if ref.kind == "point" or entity.kind == "point":
            self._move_point_to_fixed_group(self._point(ref))
            return []
        if entity.kind in {"line", "arc"}:
            point_ids = [str(entity.data["start"]), str(entity.data["end"])]
            if entity.kind == "arc":
                point_ids.append(str(entity.data["center"]))
            for point_id in point_ids:
                self._move_point_to_fixed_group(self.point_handles[point_id])
            return []
        if entity.kind == "bspline":
            for handle in self.bspline_pole_handles[ref.entity_id]:
                self._move_point_to_fixed_group(handle)
            return []
        if entity.kind == "ellipse":
            for key in ("center", "major", "minor"):
                self._move_point_to_fixed_group(
                    self.point_handles[str(entity.data[key])]
                )
            return []
        if entity.kind == "circle":
            self._move_point_to_fixed_group(self.point_handles[str(entity.data["center"])])
            self._move_entity_to_fixed_group(self.radius_entities[ref.entity_id])
            return []
        raise ValueError(f"Cannot fix sketch entity kind '{entity.kind}'")

    def _move_point_to_fixed_group(self, handle: int) -> None:
        point = self.system.getEntity(handle)
        point.group = self._FIXED_GROUP
        self.system.addEntity(point, overwrite=True)
        for index in (0, 1):
            parameter = self.system.getParam(self.system.getEntityParam(handle, index))
            parameter.group = self._FIXED_GROUP
            self.system.addParam(parameter, overwrite=True)

    def _move_entity_to_fixed_group(self, handle: int) -> None:
        entity = self.system.getEntity(handle)
        entity.group = self._FIXED_GROUP
        self.system.addEntity(entity, overwrite=True)
        parameter = self.system.getParam(self.system.getEntityParam(handle, 0))
        parameter.group = self._FIXED_GROUP
        self.system.addParam(parameter, overwrite=True)

    def _add_axis_distance(
        self,
        constraint: "SketchConstraint",
        refs: Sequence["SketchRef"],
        kind: str,
    ) -> int:
        from ..sketch import _as_float

        origin = self.system.addPoint2dV(self.workplane, 0.0, 0.0, group=self._FIXED_GROUP)
        direction = self.system.addPoint2dV(
            self.workplane,
            1.0 if kind == "distance_x" else 0.0,
            0.0 if kind == "distance_x" else 1.0,
            group=self._FIXED_GROUP,
        )
        axis = self.system.addLineSegment(origin, direction, group=self._FIXED_GROUP)
        # SolveSpace's projected-distance sign is opposite to SimpleCAD's
        # target convention (target = point_b - point_a).
        return self.system.addPointsProjectDistance(
            -_as_float(constraint.value),
            self._point(refs[0]),
            self._point(refs[1]),
            axis,
            group=self._SOLVE_GROUP,
        )

    def _initial_point(self, point_id: str) -> Tuple[float, float]:
        from ..sketch import _as_float

        entity = self.sketch.entities[point_id]
        return (
            _as_float(entity.data["x"]),
            _as_float(entity.data["y"]),
        )

    def _normal(
        self,
        constraint: "SketchConstraint",
        refs: Sequence["SketchRef"],
    ) -> Sequence[int]:
        del constraint
        entities = [self.sketch.entities[ref.entity_id] for ref in refs]
        line_index = next(
            (index for index, entity in enumerate(entities) if entity.kind == "line"),
            None,
        )
        curve_index = next(
            (
                index
                for index, entity in enumerate(entities)
                if entity.kind in {"circle", "arc"}
            ),
            None,
        )
        if line_index is None or curve_index is None:
            raise ValueError(
                "A normal constraint requires one line and one circle or arc"
            )
        # A line normal to a circle or arc passes through its center.
        return [self.system.addPointOnLine(
            self._circle_center(refs[curve_index]),
            self._entity(refs[line_index]),
            self.workplane,
            group=self._SOLVE_GROUP,
        )]

    def _mirror(
        self,
        constraint: "SketchConstraint",
        refs: Sequence["SketchRef"],
    ) -> Sequence[int]:
        del constraint
        a_entity = self.sketch.entities[refs[0].entity_id]
        b_entity = self.sketch.entities[refs[2].entity_id]
        if a_entity.kind != b_entity.kind:
            raise ValueError(
                "Mirror constraint requires two entities of the same kind, got "
                f"'{a_entity.kind}' and '{b_entity.kind}'"
            )
        axis_entity = self.sketch.entities[refs[1].entity_id]
        if axis_entity.kind != "line":
            raise ValueError("Mirror constraint requires a line as its axis")
        axis = self._entity(refs[1])
        handles: List[int] = []
        for point_a, point_b in self._mirror_point_pairs(a_entity, b_entity):
            handles.extend(self._symmetric_about_line(
                self.point_handles[point_a],
                self.point_handles[point_b],
                axis,
                self._initial_point(point_a),
                self._initial_point(point_b),
            ))
        return handles

    def _symmetric_about_line(
        self,
        p_handle: int,
        q_handle: int,
        axis_handle: int,
        p_initial: Tuple[float, float],
        q_initial: Tuple[float, float],
    ) -> Sequence[int]:
        # py-slvs' addSymmetricLine misbehaves (it mirrors about the
        # workplane u-axis regardless of the axis entity), so decompose:
        # P and Q are mirror images about the line iff the midpoint of PQ
        # lies on the line and PQ is perpendicular to it. The helper segment
        # and midpoint are solver-only construction entities.
        segment = self.system.addLineSegment(p_handle, q_handle, group=self._SOLVE_GROUP)
        midpoint = self.system.addPoint2dV(
            self.workplane,
            0.5 * (p_initial[0] + q_initial[0]),
            0.5 * (p_initial[1] + q_initial[1]),
            group=self._SOLVE_GROUP,
        )
        return [
            self.system.addMidPoint(midpoint, segment, self.workplane, group=self._SOLVE_GROUP),
            self.system.addPointOnLine(midpoint, axis_handle, self.workplane, group=self._SOLVE_GROUP),
            self.system.addPerpendicular(segment, axis_handle, self.workplane, group=self._SOLVE_GROUP),
        ]

    def _mirror_point_pairs(
        self,
        a_entity: "SketchEntity",
        b_entity: "SketchEntity",
    ) -> List[Tuple[str, str]]:
        if a_entity.kind == "circle":
            return [(str(a_entity.data["center"]), str(b_entity.data["center"]))]
        roles = ("start", "end")
        a_points = [str(a_entity.data[role]) for role in roles]
        b_points = [str(b_entity.data[role]) for role in roles]
        direct = sum(
            math.dist(self._initial_point(a), self._initial_point(b))
            for a, b in zip(a_points, b_points)
        )
        flipped = sum(
            math.dist(self._initial_point(a), self._initial_point(b))
            for a, b in zip(a_points, reversed(b_points))
        )
        if flipped < direct:
            b_points.reverse()
        pairs = list(zip(a_points, b_points))
        if a_entity.kind == "arc":
            pairs.append(
                (str(a_entity.data["center"]), str(b_entity.data["center"]))
            )
        return pairs

    def _midpoint_points(self, refs: Sequence["SketchRef"]) -> Sequence[int]:
        mid_id = self.sketch.resolve_point_id(refs[0])
        a_id = self.sketch.resolve_point_id(refs[1])
        b_id = self.sketch.resolve_point_id(refs[2])
        if len({mid_id, a_id, b_id}) != 3:
            raise ValueError(
                "A midpoint-points constraint requires three distinct points"
            )
        # M is the midpoint of A and B iff |AM| = |MB| and the two segments
        # through M are parallel; two lines sharing endpoint M that are
        # parallel are necessarily collinear. The helper lines are solver-only
        # construction entities, mirroring the tangent decomposition helpers.
        line_am = self.system.addLineSegment(
            self.point_handles[a_id], self.point_handles[mid_id],
            group=self._SOLVE_GROUP,
        )
        line_mb = self.system.addLineSegment(
            self.point_handles[mid_id], self.point_handles[b_id],
            group=self._SOLVE_GROUP,
        )
        return [
            self.system.addEqualLength(line_am, line_mb, self.workplane, group=self._SOLVE_GROUP),
            self.system.addParallel(line_am, line_mb, self.workplane, group=self._SOLVE_GROUP),
        ]

    def _line_distance(
        self,
        constraint: "SketchConstraint",
        refs: Sequence["SketchRef"],
    ) -> Sequence[int]:
        from ..sketch import _as_float

        value = _as_float(constraint.value)
        if value <= 0.0:
            raise ValueError("A line-to-line distance must be positive")
        a_entity = self.sketch.entities[refs[0].entity_id]
        b_entity = self.sketch.entities[refs[1].entity_id]
        if a_entity.kind != "line" or b_entity.kind != "line":
            raise ValueError(
                "A line-to-line distance requires two line entities"
            )
        # The minimum distance between two parallel lines equals the distance
        # from any point of one line to the other; drive line a's start point
        # against line b. SolveSpace signs the point-line distance with the
        # right side of the line direction positive, so keep the solved point
        # on its initial side by flipping the sign for the left side.
        start_id = str(a_entity.data["start"])
        b_start = self._initial_point(str(b_entity.data["start"]))
        b_end = self._initial_point(str(b_entity.data["end"]))
        probe = self._initial_point(start_id)
        direction = (b_end[0] - b_start[0], b_end[1] - b_start[1])
        cross = (
            direction[0] * (probe[1] - b_start[1])
            - direction[1] * (probe[0] - b_start[0])
        )
        signed = -value if cross >= 0.0 else value
        return [self.system.addPointLineDistance(
            signed,
            self.point_handles[start_id],
            self._entity(refs[1]),
            self.workplane,
            group=self._SOLVE_GROUP,
        )]

    def _tangent(
        self,
        constraint: "SketchConstraint",
        refs: Sequence["SketchRef"],
    ) -> Sequence[int]:
        entities = [self.sketch.entities[ref.entity_id] for ref in refs]
        kinds = [entity.kind for entity in entities]
        metadata = constraint.metadata
        selectors = [metadata.get("at_a"), metadata.get("at_b")]
        mode = str(metadata.get("mode", "external"))

        if set(kinds) == {"line", "circle"}:
            line_index = kinds.index("line")
            circle_index = kinds.index("circle")
            return self._line_circle_tangent(refs[line_index], refs[circle_index])
        if kinds == ["circle", "circle"]:
            return self._circle_circle_tangent(refs[0], refs[1], mode=mode)

        curve_indices = [index for index, kind in enumerate(kinds) if kind in {"arc", "bspline"}]
        if not curve_indices:
            raise ValueError(f"Unsupported tangent target kinds '{kinds[0]}' and '{kinds[1]}'")
        for index in curve_indices:
            if selectors[index] not in {"start", "end"}:
                raise ValueError(
                    f"Tangent constraint '{constraint.constraint_id}' requires "
                    f"at_{'a' if index == 0 else 'b'}='start' or 'end'"
                )

        if set(kinds) == {"line", "arc"}:
            arc_index = kinds.index("arc")
            line_index = kinds.index("line")
            return [self.system.addArcLineTangent(
                selectors[arc_index] == "end",
                self._entity(refs[arc_index]),
                self._entity(refs[line_index]),
                group=self._SOLVE_GROUP,
            )]
        if set(kinds) == {"line", "bspline"}:
            spline_index = kinds.index("bspline")
            line_index = kinds.index("line")
            return [self.system.addCubicLineTangent(
                selectors[spline_index] == "end",
                self._bspline_endpoint_segment(refs[spline_index], str(selectors[spline_index])),
                self._entity(refs[line_index]),
                self.workplane,
                group=self._SOLVE_GROUP,
            )]
        if all(kind in {"arc", "bspline"} for kind in kinds):
            handles = [
                self._entity(ref) if kind == "arc" else self._bspline_endpoint_segment(ref, str(selector))
                for ref, kind, selector in zip(refs, kinds, selectors)
            ]
            return [self.system.addCurvesTangent(
                selectors[0] == "end",
                selectors[1] == "end",
                handles[0],
                handles[1],
                self.workplane,
                group=self._SOLVE_GROUP,
            )]
        raise ValueError(f"Unsupported tangent target kinds '{kinds[0]}' and '{kinds[1]}'")

    def _line_circle_tangent(
        self,
        line_ref: "SketchRef",
        circle_ref: "SketchRef",
    ) -> Sequence[int]:
        center = self._circle_center(circle_ref)
        circle = self._entity(circle_ref)
        line = self._entity(line_ref)
        tangent_point = self.system.addPoint2dV(
            self.workplane,
            *self._initial_tangent_point(circle_ref, line_ref),
            group=self._SOLVE_GROUP,
        )
        radius_line = self.system.addLineSegment(center, tangent_point, group=self._SOLVE_GROUP)
        return [
            self.system.addPointOnCircle(tangent_point, circle, group=self._SOLVE_GROUP),
            self.system.addPointOnLine(tangent_point, line, self.workplane, group=self._SOLVE_GROUP),
            self.system.addPerpendicular(radius_line, line, self.workplane, group=self._SOLVE_GROUP),
        ]

    def _circle_circle_tangent(
        self,
        a_ref: "SketchRef",
        b_ref: "SketchRef",
        *,
        mode: str,
    ) -> Sequence[int]:
        center_a = self._circle_center(a_ref)
        center_b = self._circle_center(b_ref)
        tangent_point = self.system.addPoint2dV(
            self.workplane,
            *self._initial_circle_tangent_point(a_ref, b_ref, mode=mode),
            group=self._SOLVE_GROUP,
        )
        radius_a = self.system.addLineSegment(center_a, tangent_point, group=self._SOLVE_GROUP)
        radius_b = self.system.addLineSegment(center_b, tangent_point, group=self._SOLVE_GROUP)
        return [
            self.system.addPointOnCircle(tangent_point, self._entity(a_ref), group=self._SOLVE_GROUP),
            self.system.addPointOnCircle(tangent_point, self._entity(b_ref), group=self._SOLVE_GROUP),
            self.system.addParallel(radius_a, radius_b, self.workplane, group=self._SOLVE_GROUP),
        ]

    def _bspline_endpoint_segment(self, ref: "SketchRef", selector: str) -> int:
        segments = self.bspline_segment_handles.get(ref.entity_id, [])
        if not segments:
            raise ValueError(
                f"B-spline '{ref.entity_id}' is not representable by py-slvs cubic entities"
            )
        return segments[0] if selector == "start" else segments[-1]

    def _initial_tangent_point(
        self,
        circle_ref: "SketchRef",
        line_ref: "SketchRef",
    ) -> Tuple[float, float]:
        from ..sketch import _as_float

        circle = self.sketch.entities[circle_ref.entity_id]
        center_entity = self.sketch.entities[str(circle.data["center"])]
        center = (
            _as_float(center_entity.data["x"]),
            _as_float(center_entity.data["y"]),
        )
        line = self.sketch.entities[line_ref.entity_id]
        start_entity = self.sketch.entities[str(line.data["start"])]
        end_entity = self.sketch.entities[str(line.data["end"])]
        start = (_as_float(start_entity.data["x"]), _as_float(start_entity.data["y"]))
        end = (_as_float(end_entity.data["x"]), _as_float(end_entity.data["y"]))
        direction = (end[0] - start[0], end[1] - start[1])
        denominator = direction[0] * direction[0] + direction[1] * direction[1]
        if denominator <= 1e-18:
            raise ValueError("A tangent constraint requires a non-degenerate line")
        parameter = (
            (center[0] - start[0]) * direction[0]
            + (center[1] - start[1]) * direction[1]
        ) / denominator
        return (
            start[0] + parameter * direction[0],
            start[1] + parameter * direction[1],
        )

    def _initial_circle_tangent_point(
        self,
        a_ref: "SketchRef",
        b_ref: "SketchRef",
        *,
        mode: str,
    ) -> Tuple[float, float]:
        from ..sketch import _as_float

        centers: List[Tuple[float, float]] = []
        for ref in (a_ref, b_ref):
            circle = self.sketch.entities[ref.entity_id]
            center = self.sketch.entities[str(circle.data["center"])]
            centers.append((_as_float(center.data["x"]), _as_float(center.data["y"])))
        direction = (centers[1][0] - centers[0][0], centers[1][1] - centers[0][1])
        magnitude = math.hypot(*direction)
        if magnitude <= 1e-18:
            direction = (1.0, 0.0)
            magnitude = 1.0
        radius = self._initial_radius(a_ref)
        if mode == "external":
            direction_sign = 1.0
        else:
            direction_sign = (
                1.0 if radius >= self._initial_radius(b_ref) else -1.0
            )
        return (
            centers[0][0] + direction_sign * radius * direction[0] / magnitude,
            centers[0][1] + direction_sign * radius * direction[1] / magnitude,
        )

    def _point(self, ref: "SketchRef") -> int:
        return self.point_handles[self.sketch.resolve_point_id(ref)]

    def _entity(self, ref: "SketchRef") -> int:
        try:
            return self.entity_handles[ref.entity_id]
        except KeyError as exc:
            raise ValueError(
                f"Sketch entity '{ref.entity_id}' is not supported by py-slvs constraints"
            ) from exc

    def _line_endpoint(self, ref: "SketchRef", endpoint: str) -> int:
        entity = self.sketch.entities[ref.entity_id]
        return self.point_handles[str(entity.data[endpoint])]

    def _circle_center(self, ref: "SketchRef") -> int:
        entity = self.sketch.entities[ref.entity_id]
        if entity.kind not in {"circle", "arc", "ellipse"}:
            raise ValueError(f"Entity '{ref.entity_id}' has no circular center")
        return self.point_handles[str(entity.data["center"])]
    def _initial_radius(self, ref: "SketchRef") -> float:
        from ..sketch import _as_float

        entity = self.sketch.entities[ref.entity_id]
        if entity.kind == "circle":
            return _as_float(entity.data["radius"])
        center = self.sketch.entities[str(entity.data["center"])]
        start = self.sketch.entities[str(entity.data["start"])]
        return math.dist(
            (_as_float(center.data["x"]), _as_float(center.data["y"])),
            (_as_float(start.data["x"]), _as_float(start.data["y"])),
        )
    def _solved_points(self) -> Dict[str, Tuple[float, float]]:
        points = {
            point_id: self._point_coordinates(handle)
            for point_id, handle in self.point_handles.items()
        }
        for entity_id, handles in self.bspline_pole_handles.items():
            for index, handle in enumerate(handles):
                points[f"bspline:{entity_id}:pole:{index}"] = self._point_coordinates(handle)
        return points

    def _point_coordinates(self, handle: int) -> Tuple[float, float]:
        return (
            float(self.system.getParam(self.system.getEntityParam(handle, 0)).val),
            float(self.system.getParam(self.system.getEntityParam(handle, 1)).val),
        )

    def _solved_scalars(
        self,
        points: Mapping[str, Tuple[float, float]],
    ) -> Dict[str, float]:
        scalars: Dict[str, float] = {}
        for entity_id, distance_handle in self.radius_entities.items():
            scalars[f"circle:{entity_id}:radius"] = float(
                self.system.getParam(
                    self.system.getEntityParam(distance_handle, 0)
                ).val
            )
        for entity_id in self.sketch.entity_order:
            entity = self.sketch.entities[entity_id]
            if entity.kind == "arc":
                center = points[str(entity.data["center"])]
                start = points[str(entity.data["start"])]
                radius = math.dist(center, start)
                scalars[f"arc:{entity_id}:radius"] = radius
                scalars[f"arc:{entity_id}:diameter"] = 2.0 * radius
        return scalars

    def _solved_entities(
        self,
        points: Mapping[str, Tuple[float, float]],
        scalars: Mapping[str, float],
    ) -> Dict[str, Dict[str, object]]:
        entities: Dict[str, Dict[str, object]] = {}
        for entity_id in self.sketch.entity_order:
            entity = self.sketch.entities[entity_id]
            if entity.kind == "point":
                entities[entity_id] = {
                    "kind": "point",
                    "point": points[entity_id],
                }
            elif entity.kind == "line":
                start = points[str(entity.data["start"])]
                end = points[str(entity.data["end"])]
                entities[entity_id] = {
                    "kind": "line",
                    "start": start,
                    "end": end,
                    "length": math.dist(start, end),
                }
            elif entity.kind == "circle":
                radius = scalars[f"circle:{entity_id}:radius"]
                entities[entity_id] = {
                    "kind": "circle",
                    "center": points[str(entity.data["center"])],
                    "radius": radius,
                    "diameter": 2.0 * radius,
                }
            elif entity.kind == "arc":
                center = points[str(entity.data["center"])]
                start = points[str(entity.data["start"])]
                end = points[str(entity.data["end"])]
                start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
                end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
                radius = scalars.get(f"arc:{entity_id}:radius", math.dist(center, start))
                sweep = (end_angle - start_angle) % (2.0 * math.pi)
                entities[entity_id] = {
                    "kind": "arc",
                    "center": center,
                    "start": start,
                    "end": end,
                    "radius": radius,
                    "sweep": sweep,
                    "length": radius * sweep,
                }
            elif entity.kind == "ellipse":
                center = points[str(entity.data["center"])]
                major = points[str(entity.data["major"])]
                minor = points[str(entity.data["minor"])]
                major_radius = math.dist(center, major)
                minor_radius = math.dist(center, minor)
                entities[entity_id] = {
                    "kind": "ellipse",
                    "center": center,
                    "major_point": major,
                    "minor_point": minor,
                    "major_radius": major_radius,
                    "minor_radius": minor_radius,
                    "angle": math.degrees(
                        math.atan2(major[1] - center[1], major[0] - center[0])
                    ),
                }
            elif entity.kind == "bspline":
                poles = [
                    points[f"bspline:{entity_id}:pole:{index}"]
                    for index in range(len(entity.data["control_points"]))
                ]
                entities[entity_id] = {
                    "kind": "bspline",
                    "degree": int(entity.data["degree"]),
                    "control_points": poles,
                    "knots": list(entity.data["knots"]),
                    "multiplicities": list(entity.data["multiplicities"]),
                    "weights": entity.data.get("weights"),
                    "periodic": bool(entity.data.get("periodic", False)),
                    "segment_count": len(self.bspline_segment_handles[entity_id]),
                }
                entities[entity_id]["solver_representation"] = self.bspline_solver_modes[entity_id]
        return entities

    def _failed_constraint_ids(self) -> List[str]:
        return list(
            dict.fromkeys(
                self.constraint_ids[handle]
                for handle in map(int, self.system.Failed)
                if handle in self.constraint_ids
            )
        )

    def _add_measurements(
        self,
        points: Mapping[str, Tuple[float, float]],
        scalars: Dict[str, float],
    ) -> None:
        for constraint in self._measurement_constraints:
            refs = self.sketch._constraint_refs(constraint)
            key = f"constraint:{constraint.constraint_id}:value"
            if constraint.kind == "distance":
                scalars[key] = math.dist(
                    self._point_value(refs[0], points),
                    self._point_value(refs[1], points),
                )
            elif constraint.kind == "distance_x":
                a = self._point_value(refs[0], points)
                b = self._point_value(refs[1], points)
                scalars[key] = b[0] - a[0]
            elif constraint.kind == "distance_y":
                a = self._point_value(refs[0], points)
                b = self._point_value(refs[1], points)
                scalars[key] = b[1] - a[1]
            elif constraint.kind == "length":
                entity = self.sketch.entities[refs[0].entity_id]
                if entity.kind == "bspline":
                    scalars[key] = self._measure_bspline_length(refs[0], points)
                elif entity.kind == "arc":
                    radius = math.dist(
                        points[str(entity.data["center"])],
                        points[str(entity.data["start"])],
                    )
                    scalars[key] = radius * self._arc_sweep(entity, points)
                else:
                    scalars[key] = math.dist(
                        points[str(entity.data["start"])],
                        points[str(entity.data["end"])],
                    )
            elif constraint.kind in {"radius", "diameter"}:
                target = self.sketch.entities[refs[0].entity_id]
                radius_key = (
                    f"circle:{refs[0].entity_id}:radius"
                    if target.kind == "circle"
                    else f"arc:{refs[0].entity_id}:radius"
                )
                radius = self._solved_scalars(points).get(radius_key)
                if radius is None:
                    raise ValueError(f"No solved radius for '{refs[0].entity_id}'")
                scalars[key] = radius * (2.0 if constraint.kind == "diameter" else 1.0)
            elif constraint.kind in {"major_radius", "minor_radius"}:
                ellipse = self.sketch.entities[refs[0].entity_id]
                axis_key = "major" if constraint.kind == "major_radius" else "minor"
                scalars[key] = math.dist(
                    points[str(ellipse.data["center"])],
                    points[str(ellipse.data[axis_key])],
                )
            elif constraint.kind == "angle":
                scalars[key] = self._measured_angle_degrees(refs, points) % 360.0
            elif constraint.kind == "line_distance":
                scalars[key] = self._measured_line_distance(refs, points)
            else:
                raise ValueError(
                    f"Constraint kind '{constraint.kind}' cannot be used as a reference measurement"
                )

    @staticmethod
    def _arc_sweep(
        entity: object,
        points: Mapping[str, Tuple[float, float]],
    ) -> float:
        center = points[str(entity.data["center"])]
        start = points[str(entity.data["start"])]
        end = points[str(entity.data["end"])]
        start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
        end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
        return (end_angle - start_angle) % (2.0 * math.pi)

    def _measure_bspline_length(
        self,
        ref: "SketchRef",
        points: Mapping[str, Tuple[float, float]],
    ) -> float:
        entity = self.sketch.entities[ref.entity_id]
        poles = [
            points[f"bspline:{ref.entity_id}:pole:{index}"]
            for index in range(len(entity.data["control_points"]))
        ]
        weights = entity.data.get("weights")
        samples = 64
        length = 0.0
        previous = poles[0]
        for step in range(1, samples + 1):
            current = self._evaluate_bspline(
                poles,
                int(entity.data["degree"]),
                entity.data["knots"],
                entity.data["multiplicities"],
                step / samples,
                weights=weights,
            )
            length += math.dist(previous, current)
            previous = current
        return length

    @staticmethod
    def _evaluate_bspline(
        poles: Sequence[Tuple[float, float]],
        degree: int,
        unique_knots: Sequence[float],
        multiplicities: Sequence[int],
        parameter: float,
        *,
        weights: Optional[Sequence[float]] = None,
    ) -> Tuple[float, float]:
        knots = [
            value
            for value, count in zip(unique_knots, multiplicities)
            for _ in range(int(count))
        ]
        u = min(max(float(parameter), knots[degree]), knots[-degree - 1])
        if u >= knots[-degree - 1]:
            return poles[-1]
        basis = [
            1.0 if knots[index] <= u < knots[index + 1] else 0.0
            for index in range(len(knots) - 1)
        ]
        for current_degree in range(1, degree + 1):
            next_basis = []
            for index in range(len(basis) - 1):
                left_den = knots[index + current_degree] - knots[index]
                right_den = knots[index + current_degree + 1] - knots[index + 1]
                left = (
                    (u - knots[index]) / left_den * basis[index]
                    if left_den
                    else 0.0
                )
                right = (
                    (knots[index + current_degree + 1] - u) / right_den * basis[index + 1]
                    if right_den
                    else 0.0
                )
                next_basis.append(left + right)
            basis = next_basis
        resolved_weights = (
            [1.0] * len(poles)
            if weights is None
            else [float(weight) for weight in weights]
        )
        weighted_basis = [
            basis[index] * resolved_weights[index]
            for index in range(len(poles))
        ]
        denominator = sum(weighted_basis)
        if abs(denominator) <= 1e-18:
            raise ValueError("B-spline evaluation produced a zero rational denominator")
        return tuple(
            sum(weighted_basis[index] * poles[index][axis] for index in range(len(poles)))
            / denominator
            for axis in (0, 1)
        )
    def _point_value(
        self,
        ref: "SketchRef",
        points: Mapping[str, Tuple[float, float]],
    ) -> Tuple[float, float]:
        return points[self.sketch.resolve_point_id(ref)]

    def _measured_angle_degrees(
        self,
        refs: Sequence["SketchRef"],
        points: Mapping[str, Tuple[float, float]],
    ) -> float:
        directions = []
        for ref in refs:
            entity = self.sketch.entities[ref.entity_id]
            start = points[str(entity.data["start"])]
            end = points[str(entity.data["end"])]
            directions.append((end[0] - start[0], end[1] - start[1]))
        cross = directions[0][0] * directions[1][1] - directions[0][1] * directions[1][0]
        dot = directions[0][0] * directions[1][0] + directions[0][1] * directions[1][1]
        return math.degrees(math.atan2(cross, dot))

    def _measured_line_distance(
        self,
        refs: Sequence["SketchRef"],
        points: Mapping[str, Tuple[float, float]],
    ) -> float:
        b_entity = self.sketch.entities[refs[1].entity_id]
        b_start = points[str(b_entity.data["start"])]
        b_end = points[str(b_entity.data["end"])]
        a_entity = self.sketch.entities[refs[0].entity_id]
        probe = points[str(a_entity.data["start"])]
        direction = (b_end[0] - b_start[0], b_end[1] - b_start[1])
        length = math.hypot(*direction)
        if length <= 1e-18:
            raise ValueError("A line-distance measurement requires a non-degenerate line")
        return abs(
            (
                direction[0] * (probe[1] - b_start[1])
                - direction[1] * (probe[0] - b_start[0])
            )
            / length
        )

    @staticmethod
    def _failure_description(result_code: int) -> Tuple[str, str]:
        return {
            _RESULT_INCONSISTENT: (
                "inconsistent_constraint",
                "Sketch constraints are inconsistent.",
            ),
            _RESULT_DIDNT_CONVERGE: (
                "did_not_converge",
                "Sketch solver did not converge.",
            ),
            _RESULT_TOO_MANY_UNKNOWNS: (
                "too_many_unknowns",
                "Sketch exceeds the backend's unknown-parameter limit.",
            ),
            _RESULT_INIT_ERROR: (
                "backend_init_error",
                "Sketch solver could not initialize the constraint system.",
            ),
        }.get(
            result_code,
            ("backend_failure", f"Sketch solver failed with result code {result_code}."),
        )


__all__ = ["PySlvsSketchSolverBackend"]
