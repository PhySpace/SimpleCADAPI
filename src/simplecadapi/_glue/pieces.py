"""The pieces of a body that a cut split, and what an operation does with them.

``cut_rsolid`` returns a ``Solid`` when the body stays one piece and a :class:`Pieces` list when the cut splits it (each
piece a body of the part).  Notebooks and the editor keep building on that value, so an operation that takes one shape
works on pieces too: it is applied to every piece and gives :class:`Pieces` back, in the same order.  Where it takes a
selection (``ql`` selector), the selector is resolved on every piece without its cardinality, a piece it finds nothing on
is kept as it is, and the cardinality is checked on what it found on all the pieces together.

Operations that take pieces as they are (a Part's bodies, a fillet or chamfer across them, a union that joins them) are
listed in :data:`TAKES_PIECES`; the native ones handle pieces themselves.
"""

from __future__ import annotations

from typing import Any, Callable

TAKES_PIECES = frozenset({"make_part_rpart", "fillet_rsolid", "chamfer_rsolid", "union_rsolid", "boolean_rsolidlist"})
"""Operations that read a list of pieces as such (all of them together), not one piece at a time."""

SPLITS = frozenset({"cut_rsolid", "fillet_rsolid", "chamfer_rsolid"})
"""Operations whose list result is the pieces of one body."""


class TagSplitWarning(UserWarning):
    """An operation split a tagged entity: the tag went to none of the pieces, each carries ``<tag>.split<i>``.

    A diagnostic, not a failure: a tag follows its entity as a reference does, and a split is where that ends.  Look at
    the pieces (the editor highlights them), and tag the ones you mean after the split if later code needs them.
    """


def tag_splits(values: Any, namespace: str) -> list[dict]:
    """The tag splits the operations of one cell (node ids ``<namespace>_...``) made, in the shapes *values* hold."""

    from simplecadapi._cpp import Solid, list_tag_splits

    shapes: list = []

    def collect(value: Any) -> None:
        if isinstance(value, Solid):
            shapes.append(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)
        elif type(value).__name__ == "Part":
            for body in value.bodies:
                collect(body.solid)

    for value in values:
        collect(value)
    seen: set = set()
    out: list[dict] = []
    for shape in shapes:
        try:
            rows = list_tag_splits(shape)
        except Exception:  # noqa: BLE001 - a diagnostic never fails the cell
            continue
        for row in rows:
            if not row["node_id"].startswith(namespace + "_"):
                continue
            key = (row["node_id"], row["tag"], row["source_topo_id"])
            if key not in seen:
                seen.add(key)
                out.append(row)
    return out


def split_message(row: dict) -> str:
    into = ", ".join(row["into"])
    return (f"{row['op']} split the entity tagged {row['tag']!r} into {len(row['into'])} pieces; "
            f"they carry {into} and {row['tag']!r} names none of them. Tag the pieces you mean after this operation "
            f"if later code selects them (scad.list_tag_splits(shape) lists the splits).")


class Pieces(list):
    """The solids one body was split into, in a stable order (``cut_rsolid``: by centroid)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"Pieces({list.__repr__(self)})"


def _is_selector(value: Any) -> bool:
    return type(value).__name__ == "ShapeSelector" and hasattr(value, "to_dict")


def _open(selector: Any) -> tuple[Any, dict | None]:
    """The selector without its cardinality, and the cardinality."""
    data = selector.to_dict()
    cardinality = data.pop("cardinality", None)
    return type(selector).from_dict(data), cardinality


def _check(name: str, cardinality: dict | None, found: int) -> None:
    if not cardinality:
        return
    exactly, least, most = cardinality.get("exactly"), cardinality.get("at_least"), cardinality.get("at_most")
    if (exactly is not None and found != exactly) or (least is not None and found < least) or (most is not None and found > most):
        raise ValueError(f"{name}: the selector expected {cardinality} on the pieces of the split body, found {found}")


def apply_to_pieces(name: str, function: Callable[..., Any], args: tuple, kwargs: dict) -> Pieces:
    """Run *function* once per piece of the one :class:`Pieces` argument; see the module docstring."""
    where = [("arg", i) for i, a in enumerate(args) if isinstance(a, Pieces)] + [("kw", k) for k, v in kwargs.items() if isinstance(v, Pieces)]
    if len(where) != 1:
        raise TypeError(f"{name}: one argument may be the pieces of a split body, {len(where)} are")
    side, key = where[0]
    pieces = args[key] if side == "arg" else kwargs[key]
    selectors = {("arg", i): _open(a) for i, a in enumerate(args) if _is_selector(a)}
    selectors.update({("kw", k): _open(v) for k, v in kwargs.items() if _is_selector(v)})
    found = {slot: 0 for slot in selectors}
    from ..ref import IN_PIECES

    token = IN_PIECES.set(True)
    try:
        out = _each_piece(function, pieces, side, key, args, kwargs, selectors, found)
    finally:
        IN_PIECES.reset(token)
    for slot, (_, cardinality) in selectors.items():
        if found[slot] == 0:
            raise ValueError(f"{name}: the selection found nothing on any piece of the split body")
        _check(name, cardinality, found[slot])
    return out


def _each_piece(function, pieces, side, key, args, kwargs, selectors, found) -> Pieces:
    out = Pieces()
    for piece in pieces:
        call_args, call_kwargs = list(args), dict(kwargs)
        if side == "arg":
            call_args[key] = piece
        else:
            call_kwargs[key] = piece
        untouched = False
        for slot, (selector, _) in selectors.items():
            hits = len(selector.resolve(piece))
            found[slot] += hits
            if hits == 0:
                untouched = True  # nothing of this piece is selected: the operation leaves it alone
            if slot[0] == "arg":
                call_args[slot[1]] = selector
            else:
                call_kwargs[slot[1]] = selector
        if untouched:
            out.append(piece)
            continue
        result = function(*call_args, **call_kwargs)
        if isinstance(result, list):
            out.extend(result)
        else:
            out.append(result)
    return out


def run_on_pieces(function: Callable[..., Any], args: tuple, kwargs: dict) -> Any:
    """Run an operation that takes the pieces together (:data:`TAKES_PIECES`), its selectors resolved per piece."""
    from ..ref import IN_PIECES

    token = IN_PIECES.set(True)
    try:
        return function(*args, **kwargs)
    finally:
        IN_PIECES.reset(token)


__all__ = ["Pieces", "SPLITS", "TAKES_PIECES", "TagSplitWarning", "apply_to_pieces", "run_on_pieces", "split_message", "tag_splits"]
