"""Helpers the Python graph replay (``recording/serializer.py``) calls on the operators module.

They belong to the replay engine, which moves to C++ with it; until then they sit here, written
against the same contract as the SDK's ``operators/sketch.py`` helpers of the same names.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, cast


def assert_sketch_solve_snapshot_dict_matches(
    actual: Dict[str, Any],
    snapshot: Dict[str, Any],
    *,
    tolerance: float = 1e-7,
) -> None:
    if str(actual.get("status")) != str(snapshot.get("status")):
        raise ValueError(f"Sketch solve status changed from {snapshot.get('status')!r} to {actual.get('status')!r}")
    if int(actual.get("dof", -1)) != int(snapshot.get("dof", -1)):
        raise ValueError(f"Sketch solve DOF changed from {snapshot.get('dof')!r} to {actual.get('dof')!r}")
    if abs(float(actual.get("residual_norm", 0.0)) - float(snapshot.get("residual_norm", 0.0))) > tolerance:
        raise ValueError("Sketch solve residual changed beyond recorded tolerance")

    actual_points = cast(Dict[str, Any], actual.get("solved_points", {}))
    expected_points = cast(Dict[str, Any], snapshot.get("solved_points", {}))
    if set(actual_points) != set(expected_points):
        raise ValueError("Sketch solve point set changed")
    for point_id, point in actual_points.items():
        expected = expected_points[point_id]
        if math.dist((float(point[0]), float(point[1])), (float(expected[0]), float(expected[1]))) > tolerance:
            raise ValueError(f"Sketch solve point '{point_id}' changed beyond recorded tolerance")

    actual_scalars = cast(Dict[str, Any], actual.get("solved_scalars", {}))
    expected_scalars = cast(Dict[str, Any], snapshot.get("solved_scalars", {}))
    if set(actual_scalars) != set(expected_scalars):
        raise ValueError("Sketch solve scalar set changed")
    for scalar_id, value in actual_scalars.items():
        if abs(float(value) - float(expected_scalars[scalar_id])) > tolerance:
            raise ValueError(f"Sketch solve scalar '{scalar_id}' changed beyond recorded tolerance")

    actual_entities = cast(Dict[str, Any], actual.get("solved_entities", {}))
    expected_entities = cast(Dict[str, Any], snapshot.get("solved_entities", {}))
    if set(actual_entities) != set(expected_entities):
        raise ValueError("Sketch solve entity set changed")
    for entity_id, entity in actual_entities.items():
        _solved_value_matches(entity, expected_entities[entity_id], tolerance, f"Sketch solve entity '{entity_id}'")


def _solved_value_matches(actual: Any, expected: Any, tolerance: float, path: str) -> None:
    if isinstance(actual, Mapping) and isinstance(expected, Mapping):
        if set(actual) != set(expected):
            raise ValueError(f"{path} field set changed")
        for key, value in actual.items():
            _solved_value_matches(value, expected[key], tolerance, f"{path}.{key}")
        return
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        if len(actual) != len(expected):
            raise ValueError(f"{path} sequence length changed")
        for index, value in enumerate(actual):
            _solved_value_matches(value, expected[index], tolerance, f"{path}[{index}]")
        return
    if (
        isinstance(actual, (int, float))
        and not isinstance(actual, bool)
        and isinstance(expected, (int, float))
        and not isinstance(expected, bool)
    ):
        if abs(float(actual) - float(expected)) > tolerance:
            raise ValueError(f"{path} changed beyond recorded tolerance")
        return
    if actual != expected:
        raise ValueError(f"{path} changed")


def load_brep_region_rshape(nat: Any):
    """``_load_brep_region_rshape(path, sha256, *, root_kind, tag_prefix, replay_root)`` over the native loaders."""

    def load(path: Any, sha256: str, *, root_kind: str, tag_prefix: Any = None, replay_root: Any = None) -> Any:
        loader = nat.load_brep_region_rsolid if root_kind == "solid" else nat.load_brep_region_rshell
        return loader(path, sha256, tag_prefix=tag_prefix)

    return load
