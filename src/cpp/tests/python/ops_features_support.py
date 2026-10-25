"""Shared plumbing of the ops_features parity tests.

A scenario is a snippet of Python written against `scad` (the public operator API, which the
reference SDK and this port spell alike).  `compare` runs it twice -- in the reference
interpreter, recorded once into tests/golden/ops_features_<name>.json by `ref.golden`, and here
against the port -- and requires the same JSON answer.

Shapes are described order-independently (a multiset of faces by area, centre and tags), because
only the geometry and the tags that follow it are the contract, not the kernel's enumeration order.
"""

from __future__ import annotations

import textwrap

from ref import GEOMETRY_REL, close, golden

import simplecadapi._cpp as port

PRELUDE = '''
import math
ql = scad.ql

def faces_of(s): return ql.faces().resolve(s)
def edges_of(s): return ql.edges().resolve(s)
def tags_of(s): return sorted(s._list_tags())
def num(x): return float(x)

def face_row(f):
    c = f.get_center()
    return [[round(f.get_area(), 4), round(c.x, 3), round(c.y, 3), round(c.z, 3)], tags_of(f)]

def edge_row(e):
    c = e.get_center()
    return [[round(e.get_length(), 4), round(c.x, 3), round(c.y, 3), round(c.z, 3)], tags_of(e)]

def describe(s, detail=True):
    faces, edges = faces_of(s), edges_of(s)
    verts = [[num(v) for v in p.get_coordinates()] for p in ql.vertices().resolve(s)]
    out = {
        "volume": num(s.get_volume()),
        "area": sum(num(f.get_area()) for f in faces),
        "faces": len(faces),
        "edges": len(edges),
        "bbox": [min(v[i] for v in verts) for i in range(3)] + [max(v[i] for v in verts) for i in range(3)],
        "tags": tags_of(s),
    }
    if detail:
        out["face_rows"] = sorted(map(face_row, faces), key=lambda r: r[0])
        out["edge_rows"] = sorted(map(edge_row, edges), key=lambda r: r[0])
    return out

def centroid(s):
    pts = [[num(v) for v in p.get_coordinates()] for p in ql.vertices().resolve(s)]
    return [round(sum(p[i] for p in pts) / len(pts), 6) for i in range(3)]

def failure(call, details=True):
    try:
        call()
    except scad.SimpleCADError as e:
        d = e.to_dict()
        keep = ("operation", "what_happened", "possible_causes", "how_to_fix", "technical_details",
                "measurements", "repair", "inventory")
        return {k: d[k] for k in keep if details or k != "technical_details"}
    return None
'''


def run_port(snippet: str):
    namespace = {"scad": port, "result": None}
    exec(PRELUDE + snippet, namespace)
    return namespace["result"]


def compare(name: str, *parts: str, rel: float = GEOMETRY_REL, abs_: float = 1e-7):
    snippet = "\n".join(textwrap.dedent(part) for part in parts)
    expected = golden("ops_features_" + name, PRELUDE + snippet)
    actual = run_port(snippet)
    assert close(actual, expected, rel, abs_), _diff(actual, expected)


def _diff(actual, expected, path="result"):
    if isinstance(actual, dict) and isinstance(expected, dict):
        for key in sorted(set(actual) | set(expected)):
            if key not in actual or key not in expected:
                return f"{path}.{key}: only in {'port' if key in actual else 'reference'}"
            if not close(actual[key], expected[key]):
                return _diff(actual[key], expected[key], f"{path}.{key}")
    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            return f"{path}: length {len(actual)} != {len(expected)}"
        for i, (a, b) in enumerate(zip(actual, expected)):
            if not close(a, b):
                return _diff(a, b, f"{path}[{i}]")
    return f"{path}: port {actual!r} != reference {expected!r}"


def parameter_names(function) -> list[str]:
    """Argument names: the signature of the SDK wrapper, else a pybind11 docstring `name(a: T, b: T = 1, *, c: T = None) -> R`."""
    import inspect

    try:
        return [p.name for p in inspect.signature(function).parameters.values()]
    except (TypeError, ValueError):
        pass
    signature = function.__doc__.splitlines()[0]
    inside = signature[signature.index("(") + 1: signature.rindex(")")] if "->" not in signature else \
        signature[signature.index("(") + 1: signature.rindex(")", 0, signature.rindex("->"))]
    names, depth, current = [], 0, ""
    for ch in inside + ",":
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            token = current.strip()
            current = ""
            if token and token not in ("*", "/"):
                names.append(token.split(":")[0].split("=")[0].strip().lstrip("*"))
        else:
            current += ch
    return names
