"""Assembly constraint values and reports."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Tuple

from .._internal.semantic import (
    SemanticValueMixin,
    _finite_float,
    _optional_float,
    _optional_positive_float,
    _validate_identifier,
)
from .connector import ConnectorRef

ConstraintKind = str

@dataclass(frozen=True)
class ScalarLimit(SemanticValueMixin):
    """Closed scalar range for a constraint drive coordinate."""

    lower_value: float
    upper_value: float
    _metadata: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)
    _runtime: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        lower = _finite_float(self.lower_value, field_name="lower_value")
        upper = _finite_float(self.upper_value, field_name="upper_value")
        if lower > upper:
            raise ValueError("lower_value must be less than or equal to upper_value")
        object.__setattr__(self, "lower_value", lower)
        object.__setattr__(self, "upper_value", upper)

    def contains(self, value: float) -> bool:
        scalar = _finite_float(value, field_name="value")
        return self.lower_value <= scalar <= self.upper_value

    def to_dict(self) -> Dict[str, Any]:
        return {"lower_value": self.lower_value, "upper_value": self.upper_value}


@dataclass(frozen=True)
class Constraint(SemanticValueMixin):
    """Connector-to-connector assembly constraint."""

    constraint_id: str
    constraint_kind: ConstraintKind
    connector_a: ConnectorRef
    connector_b: ConnectorRef
    drive_distance: Optional[float] = None
    distance_limit: Optional[ScalarLimit] = None
    drive_angle_degrees: Optional[float] = None
    angle_limit: Optional[ScalarLimit] = None
    pitch_radius_a: Optional[float] = None
    pitch_radius_b: Optional[float] = None
    pulley_radius_a: Optional[float] = None
    pulley_radius_b: Optional[float] = None
    pitch_radius: Optional[float] = None
    phase_offset: Optional[float] = None
    name: Optional[str] = None
    _metadata: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)
    _runtime: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "constraint_id",
            _validate_identifier(self.constraint_id, field_name="constraint_id"),
        )
        kind = str(self.constraint_kind).strip().lower()
        if kind not in {"fixed", "revolute", "prismatic", "gear", "belt", "rack_pinion"}:
            raise ValueError(
                "constraint_kind must be fixed, revolute, prismatic, gear, belt, or rack_pinion"
            )
        object.__setattr__(self, "constraint_kind", kind)
        if not isinstance(self.connector_a, ConnectorRef):
            raise TypeError("connector_a must be a ConnectorRef")
        if not isinstance(self.connector_b, ConnectorRef):
            raise TypeError("connector_b must be a ConnectorRef")
        if self.connector_a == self.connector_b:
            raise ValueError("constraint cannot connect the same connector ref twice")
        drive_distance = _optional_float(self.drive_distance, field_name="drive_distance")
        drive_angle = _optional_float(
            self.drive_angle_degrees, field_name="drive_angle_degrees"
        )
        if self.distance_limit is not None and not isinstance(self.distance_limit, ScalarLimit):
            raise TypeError("distance_limit must be a ScalarLimit")
        if self.angle_limit is not None and not isinstance(self.angle_limit, ScalarLimit):
            raise TypeError("angle_limit must be a ScalarLimit")
        pitch_radius_a = _optional_positive_float(
            self.pitch_radius_a, field_name="pitch_radius_a"
        )
        pitch_radius_b = _optional_positive_float(
            self.pitch_radius_b, field_name="pitch_radius_b"
        )
        pulley_radius_a = _optional_positive_float(
            self.pulley_radius_a, field_name="pulley_radius_a"
        )
        pulley_radius_b = _optional_positive_float(
            self.pulley_radius_b, field_name="pulley_radius_b"
        )
        pitch_radius = _optional_positive_float(
            self.pitch_radius, field_name="pitch_radius"
        )
        phase_offset = _optional_float(self.phase_offset, field_name="phase_offset")
        if kind in {"fixed", "revolute", "prismatic"}:
            if any(
                value is not None
                for value in (
                    pitch_radius_a,
                    pitch_radius_b,
                    pulley_radius_a,
                    pulley_radius_b,
                    pitch_radius,
                    phase_offset,
                )
            ):
                raise ValueError(
                    f"{kind} constraints do not accept coupling radii or phase_offset"
                )
        if kind == "fixed":
            if drive_distance is not None or drive_angle is not None:
                raise ValueError("fixed constraints do not accept drive scalars")
            if self.distance_limit is not None or self.angle_limit is not None:
                raise ValueError("fixed constraints do not accept scalar limits")
        if kind == "revolute":
            if drive_distance is not None or self.distance_limit is not None:
                raise ValueError("revolute constraints only accept angle scalars")
        if kind == "prismatic":
            if drive_angle is not None or self.angle_limit is not None:
                raise ValueError("prismatic constraints only accept distance scalars")
        if kind in {"gear", "belt", "rack_pinion"}:
            if drive_distance is not None or drive_angle is not None:
                raise ValueError(f"{kind} constraints do not accept drive scalars")
            if self.distance_limit is not None or self.angle_limit is not None:
                raise ValueError(f"{kind} constraints do not accept scalar limits")
            if phase_offset is None:
                phase_offset = 0.0
        if kind == "gear":
            if pitch_radius_a is None or pitch_radius_b is None:
                raise ValueError("gear constraints require pitch_radius_a and pitch_radius_b")
            if pulley_radius_a is not None or pulley_radius_b is not None or pitch_radius is not None:
                raise ValueError("gear constraints only accept pitch_radius_a and pitch_radius_b")
        if kind == "belt":
            if pulley_radius_a is None or pulley_radius_b is None:
                raise ValueError("belt constraints require pulley_radius_a and pulley_radius_b")
            if pitch_radius_a is not None or pitch_radius_b is not None or pitch_radius is not None:
                raise ValueError("belt constraints only accept pulley_radius_a and pulley_radius_b")
        if kind == "rack_pinion":
            if pitch_radius is None:
                raise ValueError("rack_pinion constraints require pitch_radius")
            if (
                pitch_radius_a is not None
                or pitch_radius_b is not None
                or pulley_radius_a is not None
                or pulley_radius_b is not None
            ):
                raise ValueError("rack_pinion constraints only accept pitch_radius")
        object.__setattr__(self, "drive_distance", drive_distance)
        object.__setattr__(self, "drive_angle_degrees", drive_angle)
        object.__setattr__(self, "pitch_radius_a", pitch_radius_a)
        object.__setattr__(self, "pitch_radius_b", pitch_radius_b)
        object.__setattr__(self, "pulley_radius_a", pulley_radius_a)
        object.__setattr__(self, "pulley_radius_b", pulley_radius_b)
        object.__setattr__(self, "pitch_radius", pitch_radius)
        object.__setattr__(self, "phase_offset", phase_offset)
        if self.name is not None:
            name = str(self.name).strip()
            if not name:
                raise ValueError("name must not be empty when provided")
            object.__setattr__(self, "name", name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "constraint_kind": self.constraint_kind,
            "connector_a": self.connector_a.to_dict(),
            "connector_b": self.connector_b.to_dict(),
            "drive_distance": self.drive_distance,
            "distance_limit": self.distance_limit.to_dict() if self.distance_limit else None,
            "drive_angle_degrees": self.drive_angle_degrees,
            "angle_limit": self.angle_limit.to_dict() if self.angle_limit else None,
            "pitch_radius_a": self.pitch_radius_a,
            "pitch_radius_b": self.pitch_radius_b,
            "pulley_radius_a": self.pulley_radius_a,
            "pulley_radius_b": self.pulley_radius_b,
            "pitch_radius": self.pitch_radius,
            "phase_offset": self.phase_offset,
            "name": self.name,
        }


@dataclass(frozen=True)
class ConstraintResidual:
    """Residual for a single assembly constraint."""

    constraint_id: str
    translation_error: float
    angular_error_degrees: float
    within_tolerance: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "translation_error": self.translation_error,
            "angular_error_degrees": self.angular_error_degrees,
            "within_tolerance": self.within_tolerance,
        }


@dataclass(frozen=True)
class ConstraintReport:
    """Assembly constraint inspection report."""

    solved: bool
    grounded_component_ids: Tuple[str, ...]
    solved_component_ids: Tuple[str, ...]
    unsolved_component_ids: Tuple[str, ...]
    residuals: Tuple[ConstraintResidual, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "solved": self.solved,
            "grounded_component_ids": list(self.grounded_component_ids),
            "solved_component_ids": list(self.solved_component_ids),
            "unsolved_component_ids": list(self.unsolved_component_ids),
            "residuals": [residual.to_dict() for residual in self.residuals],
        }


def _validate_constraints(constraints: Iterable[Constraint]) -> Tuple[Constraint, ...]:
    result = tuple(constraints or ())
    for constraint in result:
        if not isinstance(constraint, Constraint):
            raise TypeError("constraints must contain Constraint values")
    ids = [constraint.constraint_id for constraint in result]
    duplicates = sorted(constraint_id for constraint_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError("duplicate constraint_id: " + ", ".join(duplicates))
    return result


def _is_coupling_constraint(constraint: Constraint) -> bool:
    return constraint.constraint_kind in {"gear", "belt", "rack_pinion"}


def _is_connecting_constraint(constraint: Constraint) -> bool:
    return not _is_coupling_constraint(constraint)


__all__ = [
    "Constraint",
    "ConstraintReport",
    "ConstraintResidual",
    "ScalarLimit",
]
