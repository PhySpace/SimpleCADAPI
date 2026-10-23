"""Operators of the ``selection`` group.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_semantic.cpp`` -> ``src/cpp/src/semantic``
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_semantic.cpp
    apply_tag,
    apply_tag_rselection,
    explain_tag,
    list_tags,
    select_edges_by_tag,
    select_faces_by_tag,
)

__all__ = [
    "apply_tag",
    "apply_tag_rselection",
    "explain_tag",
    "list_tags",
    "select_edges_by_tag",
    "select_faces_by_tag",
]
