"""
measurements for the geometry parity tests
"""
from __future__ import annotations
import simplecadapi._cpp._native
import typing
__all__: list[str] = ['bbox', 'counts', 'sample']
def bbox(arg0: simplecadapi._cpp._native.AnyShape) -> typing.Annotated[list[float], "FixedSize(6)"]:
    ...
def counts(arg0: simplecadapi._cpp._native.AnyShape) -> dict:
    ...
def sample(arg0: simplecadapi._cpp._native.Edge, arg1: typing.SupportsInt | typing.SupportsIndex) -> list[typing.Annotated[list[float], "FixedSize(3)"]]:
    ...
