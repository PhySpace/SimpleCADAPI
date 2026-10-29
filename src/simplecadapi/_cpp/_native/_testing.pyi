"""
helpers for the test suite
"""
from __future__ import annotations
import simplecadapi._cpp._native
import typing
__all__: list[str] = ['box', 'cylinder']
def box(arg0: typing.SupportsFloat | typing.SupportsIndex, arg1: typing.SupportsFloat | typing.SupportsIndex, arg2: typing.SupportsFloat | typing.SupportsIndex) -> simplecadapi._cpp._native.Solid:
    ...
def cylinder(arg0: typing.SupportsFloat | typing.SupportsIndex, arg1: typing.SupportsFloat | typing.SupportsIndex) -> simplecadapi._cpp._native.Solid:
    ...
