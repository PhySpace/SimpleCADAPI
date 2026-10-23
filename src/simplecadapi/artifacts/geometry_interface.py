"""Stable geometry-interface descriptors independent of raw BRep bytes (computed from what the C++ handles measure)."""

from __future__ import annotations

from collections import Counter, OrderedDict
from typing import Any, Dict, List, Tuple

import simplecadapi._cpp as _n

from . import canonical as _canonical
from .canonical import canonical_bytes, content_hash

_GEOMETRY_INTERFACE_PROFILE = "simplecad-geometry-interface-1"
_DEFAULT_TOLERANCE = 1.0e-7
_BOUNDS_QUANTUM = 1.0e-4
_TOLERANCE_PROFILES = {
    "simplecad-default": _DEFAULT_TOLERANCE,
    "simplecad-strict": 1.0e-9,
    "simplecad-coarse": 1.0e-6,
}


def _tolerance_for_profile(profile: str) -> float:
    if not isinstance(profile, str) or not profile:
        raise ValueError("tolerance_profile must be a non-empty string")
    return _TOLERANCE_PROFILES.get(profile, _DEFAULT_TOLERANCE)


def _enum_suffix(value: Any, prefix: str) -> str:
    return str(value).split(".")[-1].removeprefix(prefix)


def _q(value: float, tolerance: float) -> int:
    return int(round(float(value) / tolerance))


def _qvec(values: Any, tolerance: float) -> tuple[int, ...]:
    return tuple(_q(float(value), tolerance) for value in values)


_JSON_SAFE_INT = 9_007_199_254_740_991


def _json_safe(value: Any) -> Any:
    """Quantized ints of large bodies (a 36 m slab's volume / 1e-7) pass the JSON safe range; hash them as
    decimal strings. Labels stay ints until here, so sorting and in-range hashes are unchanged."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return f"int:{value}" if abs(value) > _JSON_SAFE_INT else value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_json_safe(item) for item in value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _hash(payload: Any) -> str:
    if _canonical._NATIVE is not None:
        fast = _canonical._NATIVE.canonical_hash(payload, (), True)
        if fast is not None:
            return fast
    return content_hash(_json_safe(payload), omit=())




def _vec(value: Any) -> Tuple[float, float, float]:
    return (float(value.x), float(value.y), float(value.z))


def _union(boxes: List[Tuple[float, ...]]) -> Tuple[float, ...]:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        min(b[2] for b in boxes),
        max(b[3] for b in boxes),
        max(b[4] for b in boxes),
        max(b[5] for b in boxes),
    )


def _raw_bounds(handle: Any, cache: Dict[Any, Tuple[float, ...]] | None = None) -> Tuple[float, ...]:
    """The shape's box.  A solid / shell / wire box is exactly (bitwise: checked on every arm6 shape) the union
    of its faces' / edges' boxes, because ``AddOptimal`` measures each face and edge on its own; the faces
    of a drilled torus take 14 ms each, so a body measured on its own repeats all of them."""

    kind = type(handle).__name__
    if kind in ("Solid", "Shell"):
        parts = [_raw_bounds(face, cache) for face in handle._iter_faces()]
    elif kind == "Wire":
        parts = [_raw_bounds(edge, cache) for edge in handle._iter_edges()]
    else:
        parts = []
    if parts:
        return _union(parts)
    if cache is None:
        return tuple(handle._bounds())
    key = (kind, handle.topo_id)
    box = cache.get(key)
    if box is None:
        box = cache[key] = tuple(handle._bounds())
    return box


def _bounds(handle: Any, tolerance: float, cache: Dict[Any, Tuple[float, ...]] | None = None) -> Tuple[int, ...]:
    return tuple(_q(v, _BOUNDS_QUANTUM) for v in _raw_bounds(handle, cache))


def _label(kind: str, handle: Any, tolerance: float, cache: Dict[Any, Tuple[float, ...]] | None = None) -> Tuple[Any, ...]:
    q, qvec = _q, _qvec
    if kind == "body":
        return ("body", q(handle.get_volume(), tolerance), qvec(_vec(handle.get_center()), tolerance), _bounds(handle, tolerance, cache))
    if kind == "face":
        return (
            "face",
            handle._geom_type(),
            q(handle.get_area(), tolerance),
            qvec(_vec(handle.get_center()), tolerance),
            qvec(_vec(handle.get_normal_at()), tolerance),
            _bounds(handle, tolerance, cache),
        )
    if kind == "edge":
        ends = sorted(
            qvec(_vec(v.get_coordinates()) if not isinstance(v.get_coordinates(), tuple) else v.get_coordinates(), tolerance)
            for v in handle._iter_vertices()
        )
        return (
            "edge",
            handle._geom_type(),
            q(handle.get_length(), tolerance),
            qvec(_vec(handle.get_center()), tolerance),
            _bounds(handle, tolerance, cache),
            tuple(ends),
        )
    coords = handle.get_coordinates()
    coords = coords if isinstance(coords, tuple) else _vec(coords)
    return ("vertex", qvec(coords, tolerance))


def stable_topology_entity_hash(handle: Any, kind: str, *, tolerance_profile: str = "simplecad-default") -> str:
    """Hash one topology carrier by normalized geometry, never BRep bytes."""

    tolerance = _tolerance_for_profile(tolerance_profile)
    cache: Dict[Any, Tuple[float, ...]] = {}
    normalized = str(kind).lower()
    if normalized == "solid":
        geometry: Any = _label("body", handle, tolerance, cache)
    elif normalized == "shell":
        geometry = (
            "shell",
            _bounds(handle, tolerance, cache),
            tuple(sorted(_label("face", item, tolerance, cache) for item in handle._iter_faces())),
        )
    elif normalized == "wire":
        geometry = (
            "wire",
            _bounds(handle, tolerance, cache),
            tuple(sorted(_label("edge", item, tolerance, cache) for item in handle._iter_edges())),
        )
    elif normalized in {"face", "edge", "vertex"}:
        geometry = _label(normalized, handle, tolerance, cache)
    else:
        raise ValueError(f"unsupported topology entity kind: {kind}")
    return _hash({"profile": "simplecad-topology-entity-1", "kind": normalized, "geometry": geometry})


def geometry_interface_descriptor(solid: Any, *, tolerance_profile: str = "simplecad-default") -> Dict[str, Any]:
    """A traversal-independent, non-BRep-byte geometry descriptor."""

    if not isinstance(solid, _n.Solid):
        raise TypeError("solid must be a Solid")
    tolerance = _tolerance_for_profile(tolerance_profile)
    nodes: Dict[Tuple[str, str], Dict[str, Any]] = {}
    cache: Dict[Any, Tuple[float, ...]] = {}
    adjacency: Dict[Tuple[str, str], Counter] = {}

    def add(key: Tuple[str, str], kind: str, handle: Any) -> None:
        if key not in nodes:
            nodes[key] = {"kind": kind, "label": _label(kind, handle, tolerance, cache)}
            adjacency.setdefault(key, Counter())

    def link(first: Tuple[str, str], second: Tuple[str, str]) -> None:
        adjacency.setdefault(first, Counter())[second] += 1
        adjacency.setdefault(second, Counter())[first] += 1

    body = ("body", solid.topo_id)
    add(body, "body", solid)
    for face in solid._iter_faces():
        face_key = ("face", face.topo_id)
        add(face_key, "face", face)
        link(body, face_key)
        for edge in face._iter_edges():
            edge_key = ("edge", edge.topo_id)
            add(edge_key, "edge", edge)
            link(face_key, edge_key)
    for key in [key for key in nodes if key[0] == "edge"]:
        pass
    seen_edges = {key[1] for key in nodes if key[0] == "edge"}
    for face in solid._iter_faces():
        for edge in face._iter_edges():
            if ("edge", edge.topo_id) in adjacency and edge.topo_id in seen_edges:
                seen_edges.discard(edge.topo_id)
                for vertex in edge._iter_vertices():
                    vertex_key = ("vertex", vertex.topo_id)
                    add(vertex_key, "vertex", vertex)
                    link(("edge", edge.topo_id), vertex_key)

    refined: Dict[Tuple[str, str], str] = {
        key: _hash({"kind": value["kind"], "geometry": value["label"]}) for key, value in nodes.items()
    }
    for _ in range(4):
        refined = {
            key: content_hash(
                {
                    "kind": nodes[key]["kind"],
                    "self": refined[key],
                    "neighbors": sorted(
                        neighbor_hash
                        for item, multiplicity in adjacency[key].items()
                        for neighbor_hash in [refined[item]] * multiplicity
                    ),
                },
                omit=(),
            )
            for key in nodes
        }
    records: List[Dict[str, Any]] = [
        {
            "kind": value["kind"],
            "geometry": _json_safe(value["label"]),
            "refined": refined[key],
            "incidence_count": sum(adjacency[key].values()),
        }
        for key, value in nodes.items()
    ]
    records.sort(key=canonical_bytes)
    counts = Counter(value["kind"] for value in nodes.values())
    area = sum(float(face.get_area()) for face in solid._iter_faces())
    return _json_safe(
        {
            "profile": _GEOMETRY_INTERFACE_PROFILE,
            "tolerance_profile": tolerance_profile,
            "tolerance": tolerance,
            "body_count": counts["body"],
            "face_count": counts["face"],
            "edge_count": counts["edge"],
            "vertex_count": counts["vertex"],
            "bounds": _bounds(solid, tolerance, cache),
            "volume": _q(solid.get_volume(), tolerance),
            "surface_area": _q(area, tolerance),
            "centroid": _qvec(_vec(solid.get_center()), tolerance),
            "nodes": records,
        }
    )


# A part is fingerprinted several times (topology snapshot, interface hashes, projection, again after a
# cache restore of the same handle): the fingerprint depends on the geometry alone, so the last few are
# kept per OCCT shape identity.  The entry holds the solid, so the identity cannot be reused by another.
_FINGERPRINTS: "OrderedDict[Tuple[Any, ...], Tuple[Any, str]]" = OrderedDict()
_FINGERPRINT_MEMO = 64


def geometry_interface_fingerprint(solid: Any, *, tolerance_profile: str = "simplecad-default") -> str:
    if not isinstance(solid, _n.Solid):
        raise TypeError("solid must be a Solid")
    key = (solid._shape_key(), tolerance_profile)
    hit = _FINGERPRINTS.get(key)
    if hit is not None:
        _FINGERPRINTS.move_to_end(key)
        return hit[1]
    value = _hash(geometry_interface_descriptor(solid, tolerance_profile=tolerance_profile))
    _FINGERPRINTS[key] = (solid, value)
    if len(_FINGERPRINTS) > _FINGERPRINT_MEMO:
        _FINGERPRINTS.popitem(last=False)
    return value


__all__ = [
    "geometry_interface_descriptor",
    "geometry_interface_fingerprint",
    "stable_topology_entity_hash",
]
