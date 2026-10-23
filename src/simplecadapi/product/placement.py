"""Rigid placement values and frame composition helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple

from .._internal.semantic import SemanticValueMixin, _finite_float
from simplecadapi._cpp import Placement

Vec3 = Tuple[float, float, float]
_AXIS_TOLERANCE = 1e-9
_ORTHOGONAL_TOLERANCE = 1e-7
def _vec3(value: Any, *, field_name: str) -> Vec3:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{field_name} must be a 3-element tuple or list")
    return (
        _finite_float(value[0], field_name=f"{field_name}[0]"),
        _finite_float(value[1], field_name=f"{field_name}[1]"),
        _finite_float(value[2], field_name=f"{field_name}[2]"),
    )


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(value: Vec3) -> float:
    return math.sqrt(_dot(value, value))


def _normalize_axis(value: Any, *, field_name: str) -> Vec3:
    vec = _vec3(value, field_name=field_name)
    length = _norm(vec)
    if length <= _AXIS_TOLERANCE:
        raise ValueError(f"{field_name} must be a non-zero vector")
    return (vec[0] / length, vec[1] / length, vec[2] / length)




_POSITION_CHUNK_MM = 1.0e-9
_DIRECTION_CHUNK = 1.0e-9
_FRAME_KEYS = ("origin", "x_axis", "y_axis", "z_axis")
_TICK_UNIT_LENGTH = 1.0 / _DIRECTION_CHUNK


def _quantize_tick(value: float, chunk: float) -> int:
    return round(float(value) / chunk)

def _is_tick_vector(values: Any) -> bool:
    return (
        isinstance(values, (list, tuple))
        and len(values) == 3
        and all(isinstance(item, int) and not isinstance(item, bool) for item in values)
    )
def placement_ticks(value: Any) -> Dict[str, Any]:
    """Return the integer-tick identity form of a placement frame.

    Tick frames are the only representation that is hashed or persisted:
    they are exact integers, so canonical JSON bytes and content hashes are
    stable across save/load cycles regardless of floating-point noise.  The
    stored ``z_axis`` is authoritative (derived once from ``x_axis ×
    y_axis`` by :class:`Placement` at write time) and is never recomputed.
    """
    if isinstance(value, Mapping) and all(
        _is_tick_vector(value.get(key)) for key in _FRAME_KEYS
    ):
        return validate_placement_ticks(value)
    placement = value if isinstance(value, Placement) else Placement(**dict(value))
    return {
        "origin": [_quantize_tick(item, _POSITION_CHUNK_MM) for item in placement.origin],
        "x_axis": [_quantize_tick(item, _DIRECTION_CHUNK) for item in placement.x_axis],
        "y_axis": [_quantize_tick(item, _DIRECTION_CHUNK) for item in placement.y_axis],
        "z_axis": [_quantize_tick(item, _DIRECTION_CHUNK) for item in placement.z_axis],
    }


def placement_frame_mm(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a millimetre float frame from a tick (or legacy float) frame."""
    return placement_from_canonical(value).to_dict()


def validate_placement_ticks(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a persisted tick frame with exact integer arithmetic."""
    if not isinstance(value, Mapping) or set(value) != set(_FRAME_KEYS):
        raise ValueError("tick frame fields must be exactly origin/x_axis/y_axis/z_axis")
    for key in _FRAME_KEYS:
        if not _is_tick_vector(value[key]):
            raise ValueError(f"{key} must be three integer ticks")
    squared = {
        name: sum(item * item for item in value[name])
        for name in ("x_axis", "y_axis", "z_axis")
    }
    max_error = 2.0e-6 * _TICK_UNIT_LENGTH
    for name, total in squared.items():
        low = (_TICK_UNIT_LENGTH - max_error) ** 2
        high = (_TICK_UNIT_LENGTH + max_error) ** 2
        if not low <= total <= high:
            raise ValueError(f"{name} must be a unit direction in tick form")
    dot = sum(a * b for a, b in zip(value["x_axis"], value["y_axis"]))
    if abs(dot) > 2.0e-6 * _TICK_UNIT_LENGTH**2:
        raise ValueError("x_axis and y_axis must be orthogonal in tick form")
    x, y, z = value["x_axis"], value["y_axis"], value["z_axis"]
    handedness = (
        (x[1] * y[2] - x[2] * y[1]) * z[0]
        + (x[2] * y[0] - x[0] * y[2]) * z[1]
        + (x[0] * y[1] - x[1] * y[0]) * z[2]
    )
    if handedness <= int(0.9 * _TICK_UNIT_LENGTH**3):
        raise ValueError("x_axis and y_axis must define a right-handed frame")
    return {key: list(value[key]) for key in _FRAME_KEYS}


def canonical_frame(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Tick form of a frame: persisted ticks validate in place, floats upgrade."""
    if isinstance(value, Mapping) and all(
        _is_tick_vector(value.get(key)) for key in _FRAME_KEYS
    ):
        return validate_placement_ticks(value)
    return placement_ticks(value)


def placement_from_canonical(value: Mapping[str, Any]) -> Placement:
    """Rebuild a runtime Placement from a tick frame (or a legacy float frame)."""
    if all(_is_tick_vector(value.get(key)) for key in _FRAME_KEYS):
        return Placement.from_exact_frame(
            tuple(item * _POSITION_CHUNK_MM for item in value["origin"]),
            tuple(item * _DIRECTION_CHUNK for item in value["x_axis"]),
            tuple(item * _DIRECTION_CHUNK for item in value["y_axis"]),
            tuple(item * _DIRECTION_CHUNK for item in value["z_axis"]),
        )
    frame = {key: tuple(value[key]) for key in _FRAME_KEYS if key in value}
    return Placement(**frame)


def compose_placements(parent: Placement, child: Placement) -> Placement:
    if not isinstance(parent, Placement):
        raise TypeError("parent must be a Placement")
    return parent.compose(child)


def identity_placement() -> Placement:
    return Placement((0.0, 0.0, 0.0))



def inverse_placement(placement: Placement) -> Placement:
    if not isinstance(placement, Placement):
        raise TypeError("placement must be a Placement")
    origin = placement.origin
    x_axis = placement.x_axis
    y_axis = placement.y_axis
    z_axis = placement.z_axis
    return Placement(
        origin=(-_dot(origin, x_axis), -_dot(origin, y_axis), -_dot(origin, z_axis)),
        x_axis=(x_axis[0], y_axis[0], z_axis[0]),
        y_axis=(x_axis[1], y_axis[1], z_axis[1]),
    )

def relative_placement(base: Placement, target: Placement) -> Placement:
    return inverse_placement(base).compose(target)


def rotate_z_placement(angle_degrees: float) -> Placement:
    angle = math.radians(_finite_float(angle_degrees, field_name="angle_degrees"))
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return Placement((0.0, 0.0, 0.0), x_axis=(cos_a, sin_a, 0.0), y_axis=(-sin_a, cos_a, 0.0))


def translate_z_placement(distance: float) -> Placement:
    return Placement((0.0, 0.0, _finite_float(distance, field_name="distance")))


__all__ = [
    "Placement",
    "placement_ticks",
    "validate_placement_ticks",
    "canonical_frame",
    "placement_from_canonical",
    "compose_placements",
    "identity_placement",
    "inverse_placement",
    "relative_placement",
    "rotate_z_placement",
    "translate_z_placement",
]
