"""What the cell cache makes of the values a notebook's parameters are.

``scad.var(...)`` is an object, not a number.  marimo keys a cell by the
values it reads, but only for types it can hash; for any other object it
keys by the *code of the cell that made it*, and a params cell that defines
seven variables then invalidates every cell that reads any one of them
whenever one of the seven changes.  A scalar expression has a content digest
of its own (``expr_id``: the declaration, or the operation over its operands'
digests), so registering it as a type marimo can hash makes a reader depend
on what it reads.
"""

from __future__ import annotations

from typing import Any

from simplecadapi._cpp import Const, Expr, Var
from .._glue.pieces import Pieces
from ..params.expr import ScalarExprBase, _expr_signature
from ._marimo import CustomStub, register_stub


class ScalarExprStub(CustomStub):
    """Stands for a scalar expression in the cache: hashed by content, stored
    as the (small, picklable) expression itself."""

    __slots__ = ("expr",)

    def __init__(self, obj: Any) -> None:
        self.expr = obj

    def load(self, glbls: dict[str, Any]) -> Any:
        return self.expr

    @staticmethod
    def get_type() -> type:
        return ScalarExprBase

    def to_bytes(self) -> bytes:
        expr = self.expr
        return repr((type(expr).__name__, expr.expr_id, _expr_signature(expr))).encode("utf-8")


def register_scalar_stubs() -> None:
    for kind in (Const, Var, Expr):
        register_stub(kind, ScalarExprStub)


class PiecesStub(CustomStub):
    """Stands for the pieces of a split body (``scad.Pieces``) in a stored entry.

    marimo copies every list a cell defines into a plain ``list`` before it stores it, so the pieces would come back
    as a list of tools (``cut_rsolid([a, b])`` is ``a - b``) instead of pieces an operation applies to one by one.
    :class:`~simplecadapi.runtime.cache.CellCache` stores them in this stub, which marimo keeps as it is.
    """

    __slots__ = ("pieces",)

    def __init__(self, obj: Any) -> None:
        self.pieces = list(obj)

    def load(self, glbls: dict[str, Any]) -> Any:
        return Pieces(self.pieces)

    @staticmethod
    def get_type() -> type:
        return Pieces

    def to_bytes(self) -> bytes:
        return repr([getattr(piece, "content_hash", id(piece)) for piece in self.pieces]).encode("utf-8")


register_scalar_stubs()

__all__ = ["PiecesStub", "ScalarExprStub", "register_scalar_stubs"]
