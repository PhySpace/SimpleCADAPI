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

from ..params.expr import Const, Expr, ScalarExprBase, Var, _expr_signature
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


register_scalar_stubs()

__all__ = ["ScalarExprStub", "register_scalar_stubs"]
