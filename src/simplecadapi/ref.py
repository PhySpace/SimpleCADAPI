"""``scad.ref``: stable references to faces and edges, resolved through recorded history.

A reference names an entity by where it was *born*: the feature (the cell, or the editor's feature slug) and the
operation that made it, which of that feature's operations of that name feeding it (``occurrence``), and the kernel
role the operation gave it (``"box.top"``, ``"extrusion.end"``) or, for an entity without a role, its position in
that operation's output next to a ``guard`` (its geometric fingerprint).  Resolving it follows the history every
later operation recorded to the entities of the shape it is resolved in, so it survives booleans, blends, shells,
copies and parameter edits, and an operation inserted earlier in the cell does not shift it.

Make one from a picked entity, or write it::

    top = scad.ref.of(face, part)                                  # an ElementRef; repr() is its code
    top = scad.ref.face("base", "make_box_rsolid", role="box.top")
    rim = scad.ref.edge("base", "make_box_rsolid", topo="edge_1", guard=("LINE", (-20, 0, 10), 20))

Use it::

    top.one(part)                                     # the Face, or ElementRefError
    top.all(part)                                     # the entities (several only in follow="derived" mode)
    top.resolve(part)                                 # a Resolution: status, entities, candidates, bodies
    scad.ql.faces().where(scad.ql.ref(top))           # a reference as a query predicate
    scad.fillet_rsolid(part, scad.ref.edges(rim, ...), 1.0)   # the selection an operation takes

Outcomes (``Resolution.status``): ``ok`` (one entity), ``merged`` (one entity that also absorbed others: a
coplanar union), ``split`` (several pieces: an error that lists them, until ``piece=`` says which), ``lost`` (none:
``lost_at`` and ``reason`` say where and why, and with a guard the closest look-alikes are offered).  Nothing is
ever chosen silently; :meth:`ElementRef.choose` is how a person's choice is written back into the reference.

The spelling is plain keyword data, so a reference reads as what it means and a tool can parse it back
(:func:`parse`).  ``naming`` is the version of the history-naming rules the reference was made under (1 today; a
reference without it was made under version 1).
"""

from __future__ import annotations

import ast
import dataclasses
import math
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence, Tuple, Union

from . import _cpp
from .topology import element_ref as _er
from .topology.element_ref import Candidate, ElementRefError, Resolution

_ql = _cpp.ql
_native = _cpp._native if hasattr(_cpp, "_native") else None

NAMING: int = int(_er.NAMING_VERSION.rsplit("/", 1)[-1])
"""The naming version references are made under now (``scad-naming/<NAMING>``)."""

Kind = Literal["face", "edge", "vertex"]
Follow = Literal["identity", "derived"]
Guard = Union[Tuple[str, Tuple[float, float, float], float], Tuple[str, Tuple[float, float, float], float, Tuple[float, float, float]]]
"""``(geometry type, centre, size)`` or ``(geometry type, centre, size, normal)``: what the entity looked like when it
was picked (size: area of a face, length of an edge).  It never chooses between history results; it checks a
positional anchor and ranks look-alikes of a lost reference."""

_KINDS = ("face", "edge", "vertex")
_RECORD_VERSION = 1


# ---- numbers in the spelling ----------------------------------------------------------------------------------------


def _num(value: float) -> float | int:
    """A number as short as it reads: 4 decimals, integers without a point."""
    rounded = round(float(value), 4)
    if rounded == 0:
        return 0
    if rounded == int(rounded) and abs(rounded) < 1e15:
        return int(rounded)
    return rounded


def _size(value: float) -> float | int:
    text = float(f"{float(value):.6g}")
    return int(text) if text == int(text) and abs(text) < 1e15 else text


def _vector(value: Any, name: str) -> Tuple[float, float, float]:
    try:
        x, y, z = (float(v) for v in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: three numbers (x, y, z)") from exc
    return (_num(x), _num(y), _num(z))


def _check_guard(guard: Any) -> Optional[Guard]:
    if guard is None:
        return None
    if isinstance(guard, Mapping):  # the resolver's dict form
        parts: list = [guard.get("geom_type"), guard.get("center"), guard.get("size")]
        if guard.get("normal") is not None:
            parts.append(guard["normal"])
        guard = parts
    if not isinstance(guard, (tuple, list)) or len(guard) not in (3, 4) or not isinstance(guard[0], str):
        raise ValueError("guard: (geometry type, (x, y, z), size) or (geometry type, (x, y, z), size, (nx, ny, nz))")
    out: list = [guard[0].upper(), _vector(guard[1], "guard centre"), _size(float(guard[2]))]
    if len(guard) == 4:
        out.append(_vector(guard[3], "guard normal"))
    return tuple(out)  # type: ignore[return-value]


def _topo_text(kind: str, topo: str) -> str:
    """``edge_1`` for the recorded ``edge_edge_1`` (the kind is said once)."""
    doubled = f"{kind}_{kind}_"
    return topo[len(kind) + 1 :] if topo.startswith(doubled) else topo


def _topo_record(kind: str, topo: str) -> str:
    if topo.startswith(f"{kind}_{kind}_") or not topo.startswith(f"{kind}_"):
        return topo
    return f"{kind}_{topo}"


# ---- the reference --------------------------------------------------------------------------------------------------


def _check_between(between: Any) -> tuple:
    if not isinstance(between, (tuple, list)) or len(between) != 2:
        raise ValueError("between: the two faces the edge lies between, as role names or face references")
    out = []
    for item in between:
        if isinstance(item, Mapping):
            item = ElementRef.from_dict(item)
        if isinstance(item, ElementRef):
            if item.kind != "face":
                raise ValueError("between: face references only")
        elif not isinstance(item, str) or not item:
            raise ValueError("between: a face's role name or a face reference")
        out.append(item)
    return tuple(out)




@dataclass(frozen=True)
class ElementRef:
    """A stable reference to one face, edge or vertex; ``repr()`` is the code that makes it.

    Fields: ``kind``; ``feature`` and ``op`` (where the entity was born); then exactly one of ``role`` (its kernel
    role, with ``ordinal`` saying which of the entities with that role), ``topo`` (its position in that output, for an
    entity without a role; give a ``guard`` with it) or, for an edge, ``between`` (the two faces it lies between: role
    names of faces of the same ``op``, or face references); ``occurrence`` (which of the feature's ``op`` nodes
    upstream of the shape); ``slot`` (the output of that node); ``piece`` (the chosen piece when the entity has been
    split); ``follow`` (``"identity"``, or ``"derived"`` to also follow into what it generated: an edge into its fillet
    patch); ``guard``; ``digest`` (the parameters of the node, only when two nodes share its name); ``naming`` (the
    naming version).
    """

    kind: str
    feature: str = ""
    op: str = ""
    role: Optional[str] = None
    ordinal: int = 0
    topo: Optional[str] = None
    between: Optional[Tuple[Union[str, "ElementRef"], Union[str, "ElementRef"]]] = None
    occurrence: int = 0
    slot: int = 0
    piece: Optional[int] = None
    follow: str = "identity"
    guard: Optional[Guard] = None
    digest: Optional[str] = None
    naming: int = 1

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"a reference names a face, an edge or a vertex, not {self.kind!r}")
        if sum(x is not None for x in (self.role, self.topo, self.between)) != 1:
            raise ValueError("a reference names its entity by role=, by topo= or (an edge) by between=, exactly one of them")
        if self.between is not None:
            if self.kind != "edge":
                raise ValueError("between= names an edge by the two faces it lies between")
            object.__setattr__(self, "between", _check_between(self.between))
            if self.follow != "identity":
                raise ValueError("an edge named by between= is followed by identity only")
        needs_op = self.between is None or any(isinstance(item, str) for item in self.between)
        if not isinstance(self.feature, str) or not isinstance(self.op, str) or (needs_op and not self.op):
            raise ValueError("a reference needs the feature and the op the entity was made by")
        if self.follow not in ("identity", "derived"):
            raise ValueError("follow is 'identity' or 'derived'")
        for name in ("ordinal", "occurrence", "slot", "naming"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name}: a whole number >= 0")
        if self.piece is not None and (not isinstance(self.piece, int) or isinstance(self.piece, bool) or self.piece < 0):
            raise ValueError("piece: a whole number >= 0 (which piece of a split, in the order the split error lists)")
        if self.topo is not None:
            object.__setattr__(self, "topo", _topo_text(self.kind, str(self.topo)))
        object.__setattr__(self, "guard", _check_guard(self.guard))

    # -- spelling ----------------------------------------------------------------------------------------------------
    def code(self, prefix: str = "scad.ref") -> str:
        """The code that makes this reference: ``scad.ref.face("base", "make_box_rsolid", role="box.top")``."""
        args = [repr(self.feature), repr(self.op)] if self.feature or self.op else []
        if self.role is not None:
            args.append(f"role={self.role!r}")
            if self.ordinal:
                args.append(f"ordinal={self.ordinal}")
        elif self.topo is not None:
            args.append(f"topo={self.topo!r}")
        else:
            a, b = (repr(item) if isinstance(item, str) else item.code(prefix) for item in self.between or ())
            args.append(f"between=({a}, {b})")
        for name, default in (("occurrence", 0), ("slot", 0), ("piece", None), ("follow", "identity"), ("digest", None)):
            value = getattr(self, name)
            if value != default:
                args.append(f"{name}={value!r}")
        if self.guard is not None:
            args.append(f"guard={_guard_code(self.guard)}")
        if self.naming != 1:
            args.append(f"naming={self.naming}")
        return f"{prefix}.{self.kind}({', '.join(args)})"

    def __repr__(self) -> str:
        return self.code()

    def to_dict(self) -> dict[str, Any]:
        """The record (plain data): what ``ql.ref`` stores in a selector and what :meth:`from_dict` reads."""
        out: dict[str, Any] = {"v": _RECORD_VERSION}
        for item in dataclasses.fields(self):
            value = getattr(self, item.name)
            if item.name == "guard" and value is not None:
                value = [value[0], list(value[1]), value[2], *([list(value[3])] if len(value) == 4 else [])]
            elif item.name == "between" and value is not None:
                value = [face if isinstance(face, str) else face.to_dict() for face in value]
            out[item.name] = value
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ElementRef":
        names = {item.name for item in dataclasses.fields(cls)}
        unknown = set(data) - names - {"v"}
        if unknown:
            raise ValueError(f"unknown reference fields: {', '.join(sorted(unknown))}")
        return cls(**{key: value for key, value in data.items() if key in names})

    def faces(self) -> Tuple["ElementRef", "ElementRef"]:
        """The two face references of an edge named by ``between``."""
        if self.between is None:
            raise ValueError("this reference does not name an edge by the faces it lies between")
        return tuple(  # type: ignore[return-value]
            ElementRef("face", self.feature, self.op, role=item, occurrence=self.occurrence, slot=self.slot,
                       digest=self.digest, naming=self.naming) if isinstance(item, str) else item
            for item in self.between
        )

    def anchor(self) -> dict[str, Any]:
        """The stable anchor the resolver walks from (``simplecadapi.topology.element_ref``)."""
        if self.between is not None:
            raise ValueError("an edge named by between= has no anchor of its own: its faces have (faces())")
        return {
            "feature": self.feature,
            "op": self.op,
            "occurrence": self.occurrence,
            "params_digest": self.digest or "",
            "output_slot": self.slot,
            "kind": self.kind,
            "role": self.role,
            "role_ordinal": self.ordinal,
            "topo_id": _topo_record(self.kind, self.topo) if self.topo is not None else "",
            "naming": f"scad-naming/{self.naming}",
        }

    def _guard_dict(self) -> Optional[dict[str, Any]]:
        if self.guard is None:
            return None
        out = {"kind": self.kind, "geom_type": self.guard[0], "center": list(self.guard[1]), "size": float(self.guard[2])}
        if len(self.guard) == 4:
            out["normal"] = list(self.guard[3])
        return out

    def _lookalikes(self, shape: Any) -> list:
        guard = self._guard_dict()
        return _er._ranked_lookalikes(shape, guard, self.kind) if guard else []

    # -- resolving ---------------------------------------------------------------------------------------------------
    def resolve(self, shape: Any) -> Resolution:
        """Follow the reference to the entities of *shape*; never raises for a split or a lost reference."""
        if self.between is not None:
            return self._resolve_between(shape)
        resolved = _er.resolve(self.anchor(), shape, follow=self.follow, guard=self._guard_dict())
        if resolved.version_changed and self.guard is not None and resolved.status in ("ok", "merged"):
            # Made under other naming rules: the answer stands only if it still looks like what was picked.
            if any(entity._geom_type() != self.guard[0] for entity in resolved.entities):
                return Resolution("lost", [], [], list(resolved.hops), None, "version_changed", self._lookalikes(shape), [], True)
        return resolved

    def _resolve_between(self, shape: Any) -> Resolution:
        """The edges of *shape* that lie between (a piece of) each of the two faces."""
        sides = []
        hops: list = []
        merged = changed = False
        for face_ref in self.faces():
            side = face_ref.resolve(shape)
            hops.extend(side.hops)
            changed = changed or side.version_changed
            if side.status == "lost":
                return Resolution("lost", [], [], hops, side.lost_at, side.reason, self._lookalikes(shape), [], changed)
            pieces = side.entities
            if side.status == "split" and face_ref.piece is not None and face_ref.piece < len(side.candidates):
                pieces = [side.candidates[face_ref.piece].entity]
            merged = merged or side.status == "merged"
            sides.append(set(pieces))
        first, second = sides
        found = []
        for candidate in _ql.edges().resolve(shape):
            incident = list(candidate.get_incident_faces())
            if any(a in first and b in second and a != b for a in incident for b in incident):
                found.append(candidate)
        if not found:
            return Resolution("lost", [], [], hops, None, "not_adjacent", self._lookalikes(shape), [], changed)
        bodies = _er._bodies_of(shape, found)
        if len(found) == 1:
            return Resolution("merged" if merged else "ok", found, [], hops, None, None, [], bodies, changed)
        candidates = _er._geometric_order([_er._candidate(e, str(getattr(e, "topo_id", ""))) for e in found])
        return Resolution("split", found, [], hops, None, None, candidates, bodies, changed)

    def all(self, shape: Any) -> list:
        """The entities the reference names in *shape*: ``ElementRefError`` for a split (unless ``piece``) or a lost one."""
        resolved = self.resolve(shape)
        if resolved.status in ("ok", "merged"):
            return list(resolved.entities)
        if resolved.status == "split" and self.piece is not None:
            if self.piece < len(resolved.candidates):
                return [resolved.candidates[self.piece].entity]
        raise ElementRefError(resolved)

    def one(self, shape: Any) -> Any:
        """The one entity the reference names in *shape*, or ``ElementRefError``."""
        found = self.all(shape)
        if len(found) != 1:  # follow="derived" can reach several
            candidates = [_er._candidate(entity, "") for entity in found]
            raise ElementRefError(Resolution("split", found, [], [], None, None, _er._geometric_order(candidates), []))
        return found[0]

    def choose(self, choice: int, shape: Any) -> "ElementRef":
        """The reference with the person's choice written in: a piece of a split, or a look-alike of a lost one.

        *choice* indexes ``resolve(shape).candidates``.  For a split it sets ``piece``; for a lost reference it is a new
        reference made at the chosen look-alike (:func:`of`).  Anything else is a ``ValueError``.
        """
        resolved = self.resolve(shape)
        if resolved.status not in ("split", "lost") or not 0 <= choice < len(resolved.candidates):
            raise ValueError(f"nothing to choose: the reference is {resolved.status} with {len(resolved.candidates)} candidate(s)")
        if resolved.status == "split":
            return dataclasses.replace(self, piece=choice)
        return of(resolved.candidates[choice].entity, shape, follow=self.follow)

    def query(self) -> Any:
        """``ql.<kind>s().where(ql.ref(self))``: the reference as a selector."""
        return _selector(self.kind, [self])


def _guard_code(guard: Guard) -> str:
    def vec(v: Sequence[float]) -> str:
        return "(" + ", ".join(repr(_num(c)) for c in v) + ")"

    parts = [repr(guard[0]), vec(guard[1]), repr(_size(guard[2]))]
    if len(guard) == 4:
        parts.append(vec(guard[3]))
    return "(" + ", ".join(parts) + ")"


# ---- making references ----------------------------------------------------------------------------------------------


def _make(kind: str, feature: str, op: str, **fields: Any) -> ElementRef:
    return ElementRef(kind, feature, op, **fields)


def face(
    feature: str,
    op: str,
    *,
    role: Optional[str] = None,
    ordinal: int = 0,
    topo: Optional[str] = None,
    occurrence: int = 0,
    slot: int = 0,
    piece: Optional[int] = None,
    follow: Follow = "identity",
    guard: Optional[Guard] = None,
    digest: Optional[str] = None,
    naming: int = 1,
) -> ElementRef:
    """A reference to a face born in *feature* by *op*.

    Args:
        feature: The feature (cell) the face was made in: the editor's feature slug, or the cell's namespace.
        op: The operation that made it, as recorded (``"make_box_rsolid"``, ``"make_extrude_rsolid"``).
        role: Its kernel role (``"box.top"``, ``"extrusion.end"``); ``ordinal`` says which when several share it.
        ordinal: Which of the op's faces with that role (0 first).
        topo: For a face without a role: its position in the op's output (``"face_5"``); give a ``guard`` with it.
        occurrence: Which of the feature's *op* operations feeding the shape (0: the first).
        slot: The output of that operation (a multi-body result has one per body).
        piece: The chosen piece once the face has been split (in the order the split error lists them).
        follow: ``"identity"``; ``"derived"`` also follows into what the face generated.
        guard: ``(geometry type, (x, y, z), area[, normal])`` of the face when it was picked.
        digest: The operation's parameter digest, only when two operations share its name in the feature.
        naming: The naming version the reference was made under (1).

    Returns:
        ElementRef: The reference; resolve it with ``.one(shape)`` / ``.all(shape)`` / ``.resolve(shape)``.

    Examples:
        >>> top = scad.ref.face("base", "make_box_rsolid", role="box.top")
        >>> top.one(part).get_area()
    """
    return _make("face", feature, op, role=role, ordinal=ordinal, topo=topo, occurrence=occurrence, slot=slot,
                 piece=piece, follow=follow, guard=guard, digest=digest, naming=naming)


def edge(
    feature: Optional[str] = None,
    op: Optional[str] = None,
    *,
    role: Optional[str] = None,
    ordinal: int = 0,
    topo: Optional[str] = None,
    between: Optional[Tuple[Union[str, ElementRef], Union[str, ElementRef]]] = None,
    occurrence: int = 0,
    slot: int = 0,
    piece: Optional[int] = None,
    follow: Follow = "identity",
    guard: Optional[Guard] = None,
    digest: Optional[str] = None,
    naming: int = 1,
) -> ElementRef:
    """A reference to an edge: born in *feature* by *op*, or lying ``between`` two faces.

    An edge is best named by the two faces it lies between: the faces' history is recorded by every operation, so the
    edge is found again after booleans, blends and copies, and the name reads as what it is.  ``between`` holds two
    role names of faces made by *op* in *feature* (``("box.top", "box.front")``), or two face references (then
    *feature* and *op* may be left out).  The other arguments are :func:`face`'s (``guard`` size = length).

    Examples:
        >>> rim = scad.ref.edge("base", "make_box_rsolid", between=("box.top", "box.front"))
        >>> lip = scad.ref.edge(between=(scad.ref.face("base", "make_box_rsolid", role="box.top"),
        ...                              scad.ref.face("bore", "make_cylinder_rsolid", role="cylinder.side")))
        >>> rounded = scad.fillet_rsolid(part, scad.ref.edges(rim, lip), 1.0)
    """
    return _make("edge", feature or "", op or "", role=role, ordinal=ordinal, topo=topo, between=between,
                 occurrence=occurrence, slot=slot, piece=piece, follow=follow, guard=guard, digest=digest, naming=naming)


def vertex(
    feature: str,
    op: str,
    *,
    role: Optional[str] = None,
    ordinal: int = 0,
    topo: Optional[str] = None,
    occurrence: int = 0,
    slot: int = 0,
    piece: Optional[int] = None,
    guard: Optional[Guard] = None,
    digest: Optional[str] = None,
    naming: int = 1,
) -> ElementRef:
    """A reference to a vertex born in *feature* by *op* (the arguments are :func:`face`'s)."""
    return _make("vertex", feature, op, role=role, ordinal=ordinal, topo=topo, occurrence=occurrence, slot=slot,
                 piece=piece, guard=guard, digest=digest, naming=naming)


def of(entity: Any, shape: Any, *, follow: Follow = "identity", guard: bool = True) -> ElementRef:
    """The stable reference of *entity*, a face, edge or vertex of *shape* (or of a shape *shape* descends from).

    The entity is traced back through the recorded history to where it was born, so a face picked on the finished
    part is named by the box or extrusion that made it, not by the fillet that last trimmed it.  An edge is named by
    the two faces it lies between when that names it in *shape* (``between=``), else by its own birth.

    Args:
        entity: The picked face / edge / vertex.
        shape: A recorded shape (made inside a ``GraphSession`` or a notebook cell) it belongs to.
        follow: Stored in the reference (see :func:`face`).
        guard: Store the entity's geometric fingerprint (the default; needed for an entity without a kernel role).

    Returns:
        ElementRef: ``repr()`` is the code that makes the same reference.

    Raises:
        ValueError: *shape* was not recorded, or *entity* is not part of a recorded output upstream of it.
    """
    fingerprint = _er.guard_of(entity) if guard else None
    if type(entity).__name__ == "Edge" and follow == "identity":
        named = _edge_between(entity, shape, fingerprint)
        if named is not None:
            return named
    return _born(entity, shape, follow=follow, fingerprint=fingerprint)


def _born(entity: Any, shape: Any, *, follow: str = "identity", fingerprint: Any = None) -> ElementRef:
    """The reference of *entity* by its own birth (role, else position)."""
    node = _er._node_of(shape)
    anchor = _er.stable_anchor_of(entity, shape)
    kind = str(anchor["kind"]).lower()
    if kind not in _KINDS:
        raise ValueError(f"a reference names a face, an edge or a vertex, not a {kind}")
    shared = len(_cpp._native._stable_candidates(node, anchor)) > 1
    role = anchor.get("role") or None
    return ElementRef(
        kind=kind,
        feature=str(anchor["feature"]),
        op=str(anchor["op"]),
        role=role,
        ordinal=int(anchor.get("role_ordinal") or 0) if role else 0,
        topo=None if role else str(anchor["topo_id"]),
        occurrence=int(anchor.get("occurrence") or 0),
        slot=int(anchor.get("output_slot") or 0),
        follow=follow,
        guard=fingerprint,
        digest=(str(anchor.get("params_digest") or "") or None) if shared else None,
        naming=int(str(anchor.get("naming") or _er.NAMING_VERSION).rsplit("/", 1)[-1]),
    )


def _edge_between(edge_: Any, shape: Any, fingerprint: Any) -> Optional[ElementRef]:
    """*edge_* named by the two faces it lies between, if that names exactly it in *shape* (else ``None``)."""
    incident = []
    for item in edge_.get_incident_faces():
        if all(item != known for known in incident):
            incident.append(item)
    if len(incident) != 2:
        return None  # a seam, or an edge of a non-manifold shape
    try:
        a, b = (_born(item, shape) for item in incident)
    except ValueError:
        return None
    same = (a.feature, a.op, a.occurrence, a.slot, a.digest, a.naming) == (b.feature, b.op, b.occurrence, b.slot, b.digest, b.naming)
    if same and a.role and b.role and not a.ordinal and not b.ordinal:
        ref = ElementRef("edge", a.feature, a.op, between=(a.role, b.role), occurrence=a.occurrence, slot=a.slot,
                         digest=a.digest, naming=a.naming, guard=fingerprint)
    else:
        ref = ElementRef("edge", between=(a, b), guard=fingerprint)
    resolved = ref.resolve(shape)
    if resolved.status in ("ok", "merged") and len(resolved.entities) == 1 and resolved.entities[0] == edge_:
        return ref
    if resolved.status == "split":
        for index, candidate in enumerate(resolved.candidates):
            if candidate.entity == edge_:
                return dataclasses.replace(ref, piece=index)
    return None


def coerce(reference: Any) -> ElementRef:
    """An :class:`ElementRef` from a reference, its record (:meth:`ElementRef.to_dict`) or its code."""
    if isinstance(reference, ElementRef):
        return reference
    if isinstance(reference, Mapping):
        return ElementRef.from_dict(reference)
    if isinstance(reference, str):
        return parse(reference)
    raise TypeError(f"not a reference: {reference!r}")


def resolve(reference: Any, shape: Any) -> Resolution:
    """``coerce(reference).resolve(shape)``."""
    return coerce(reference).resolve(shape)


# ---- references as selections ---------------------------------------------------------------------------------------


def _flatten(refs: Sequence[Any]) -> list[ElementRef]:
    out: list[ElementRef] = []
    for item in refs:
        if isinstance(item, (list, tuple)):
            out.extend(coerce(r) for r in item)
        else:
            out.append(coerce(item))
    return out


def predicate(reference: Union[ElementRef, Mapping[str, Any], str]) -> Any:
    """A stable reference as a ``ql`` predicate (``scad.ql.ref``): keeps the entities it names in the scope.

    The reference is resolved through the recorded history of the shape the selector is resolved against, once per
    query run; a split reference (without ``piece``) or a lost one raises ``ElementRefError`` there, it never
    matches nothing silently.  The predicate stores the reference as data, so the selector serialises and replays.

    Args:
        reference: An :class:`ElementRef`, its record (``to_dict()``) or its code (``'scad.ref.face(...)'``).

    Returns:
        SerializablePredicate: Use it in ``where(...)`` of a selector resolved against one shape.

    Examples:
        >>> top = scad.ref.face("base", "make_box_rsolid", role="box.top")
        >>> scad.ql.faces().where(scad.ql.ref(top)).exactly(1).resolve(part)
    """
    return _ql._ref(coerce(reference).to_dict())


def _selector(kind: str, refs: Sequence[ElementRef]) -> Any:
    if not refs:
        raise ValueError(f"name at least one {kind}")
    wrong = [r for r in refs if r.kind != kind]
    if wrong:
        raise ValueError(f"{kind}s(...) takes {kind} references; {wrong[0].code()} is a {wrong[0].kind}")
    factory = {"face": _ql.faces, "edge": _ql.edges, "vertex": _ql.vertices}[kind]
    predicates = [predicate(r) for r in refs]
    return factory().where(predicates[0] if len(predicates) == 1 else _ql.or_(*predicates))


def faces(*refs: Union[ElementRef, Sequence[ElementRef]]) -> Any:
    """The selection of the faces the references name: ``ql.faces().where(ql.ref(r1) | ql.ref(r2) ...)``.

    Pass it where an operation takes faces (``shell_rsolid(faces_to_remove=...)``, ``apply_tag_rselection``): the
    operation resolves it in the shape it receives, and each reference raises ``ElementRefError`` there if it is split
    (without ``piece``) or lost.

    Examples:
        >>> opening = scad.ref.faces(scad.ref.face("base", "make_box_rsolid", role="box.top"))
        >>> cup = scad.shell_rsolid(base, faces_to_remove=opening, thickness=1.0)
    """
    return _selector("face", _flatten(refs))


def edges(*refs: Union[ElementRef, Sequence[ElementRef]]) -> Any:
    """The selection of the edges the references name (see :func:`faces`).

    Examples:
        >>> rims = scad.ref.edges(scad.ref.edge("base", "make_box_rsolid", topo="edge_1", guard=("LINE", (-20, 0, 10), 20)))
        >>> rounded = scad.fillet_rsolid(base, rims, 1.0)
    """
    return _selector("edge", _flatten(refs))


def vertices(*refs: Union[ElementRef, Sequence[ElementRef]]) -> Any:
    """The selection of the vertices the references name (see :func:`faces`)."""
    return _selector("vertex", _flatten(refs))


# ---- reading the spelling back --------------------------------------------------------------------------------------

_FACTORIES = {"face": "face", "edge": "edge", "vertex": "vertex"}
_SELECTIONS = {"faces": "face", "edges": "edge", "vertices": "vertex"}


def _call_name(node: ast.expr) -> Optional[str]:
    """``face`` for ``scad.ref.face`` / ``ref.face`` / ``face``."""
    if isinstance(node, ast.Attribute):
        owner = node.value
        if isinstance(owner, ast.Attribute) and owner.attr == "ref" or isinstance(owner, ast.Name) and owner.id == "ref":
            return node.attr
        return None
    if isinstance(node, ast.Name):
        return node.id
    return None


def _literal(node: ast.expr) -> Any:
    """A literal value; inside ``between=`` a face reference may stand for one."""
    if isinstance(node, ast.Call):
        return from_ast(node)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(_literal(item) for item in node.elts)
    return ast.literal_eval(node)


def from_ast(node: ast.expr) -> ElementRef:
    """The reference an expression spells (``scad.ref.face(...)``); ``ValueError`` for anything else."""
    if not isinstance(node, ast.Call):
        raise ValueError("not a reference: expected scad.ref.face(...), scad.ref.edge(...) or scad.ref.vertex(...)")
    kind = _FACTORIES.get(_call_name(node.func) or "")
    if kind is None or len(node.args) not in (0, 2):
        raise ValueError("not a reference: expected scad.ref.<face|edge|vertex>(feature, op, ...)")
    if any(kw.arg is None for kw in node.keywords):
        raise ValueError("a reference is written with literal values only")
    try:
        positional = [ast.literal_eval(arg) for arg in node.args]
        fields = {kw.arg: (_literal(kw.value) if kw.arg == "between" else ast.literal_eval(kw.value)) for kw in node.keywords}
    except (ValueError, TypeError, SyntaxError) as exc:
        raise ValueError("a reference is written with literal values only") from exc
    feature, op = positional if positional else ("", "")
    return ElementRef(kind, feature, op, **fields)


def parse(text: str) -> ElementRef:
    """The reference spelled by *text* (what :meth:`ElementRef.code` writes)."""
    return from_ast(ast.parse(text.strip(), mode="eval").body)


def parse_selection(node: ast.expr) -> Tuple[str, list[ElementRef]]:
    """``(kind, references)`` of ``scad.ref.faces(...)`` / ``edges`` / ``vertices``; ``ValueError`` otherwise."""
    if not isinstance(node, ast.Call):
        raise ValueError("not a reference selection")
    kind = _SELECTIONS.get(_call_name(node.func) or "")
    if kind is None or node.keywords:
        raise ValueError("not a reference selection: expected scad.ref.faces(...) / edges(...) / vertices(...)")
    items: list[ast.expr] = []
    for arg in node.args:
        items.extend(arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else [arg])
    refs = [from_ast(item) for item in items]
    if any(r.kind != kind for r in refs):
        raise ValueError(f"{kind}s(...) takes {kind} references only")
    return kind, refs


def selection_code(kind: str, refs: Sequence[ElementRef], prefix: str = "scad.ref") -> str:
    """The code of a selection: one reference on one line, several one per line."""
    plural = {"face": "faces", "edge": "edges", "vertex": "vertices"}[kind]
    if len(refs) == 1:
        return f"{prefix}.{plural}({refs[0].code(prefix)})"
    inner = "".join(f"\n    {r.code(prefix)}," for r in refs)
    return f"{prefix}.{plural}({inner}\n)"


# ---- the resolver ql.ref asks ---------------------------------------------------------------------------------------


def _resolve_record(scope: Any, record: Mapping[str, Any]) -> list:
    return ElementRef.from_dict(record).all(scope)


_ql._set_reference_resolver(_resolve_record)

__all__ = [
    "NAMING",
    "Candidate",
    "ElementRef",
    "ElementRefError",
    "Follow",
    "Guard",
    "Kind",
    "Resolution",
    "coerce",
    "edge",
    "edges",
    "face",
    "faces",
    "from_ast",
    "of",
    "parse",
    "parse_selection",
    "predicate",
    "resolve",
    "selection_code",
    "vertex",
    "vertices",
]
