"""What an operation's parameters mean, as types.

The bound operations declare these in their signatures (``radius: Length``, ``axis: Direction3``), and so do the Python
operations of the standard library; the stubs, the API pages and the operation catalog (:mod:`simplecadapi.catalog`) read
the meaning from there.  Each alias is the type a caller may pass (``Annotated`` only adds the meaning):

- ``Length``: a distance, mm unless a ``scad.var`` says otherwise.
- ``Angle``: an angle in degrees.
- ``Point3``: a position ``(x, y, z)``.
- ``Direction3``: a direction or an axis; its length does not matter.
- ``Vector3``: an offset; direction and length both matter.
- ``Count``: a whole number of things (copies, teeth, segments).

A plain ``float | Expr`` is a number without a unit (a factor, a tolerance).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Union

from simplecadapi._cpp import Expr

_Number = Union[float, Expr]

Length = Annotated[_Number, "length"]
Angle = Annotated[_Number, "angle"]
Point3 = Annotated[Sequence[_Number], "point3"]
Direction3 = Annotated[Sequence[_Number], "direction3"]
Vector3 = Annotated[Sequence[_Number], "vector3"]
Count = Annotated[int, "count"]

MEANINGS: dict[str, str] = {
    "Length": "length",
    "Angle": "angle",
    "Point3": "point3",
    "Direction3": "direction3",
    "Vector3": "vector3",
    "Count": "count",
}
"""The type names a signature may carry, and the meaning each stands for (what :mod:`simplecadapi.catalog` reads)."""

__all__ = ["Angle", "Count", "Direction3", "Length", "MEANINGS", "Point3", "Vector3"]
