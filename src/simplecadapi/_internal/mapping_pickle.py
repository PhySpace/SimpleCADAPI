"""Pickle support for read-only mappings (``types.MappingProxyType``).

Definitions and feature-graph artifacts freeze their mappings behind
``MappingProxyType``, which pickle and ``copy.deepcopy`` refuse.  The
notebook runtime caches cell values with pickle, and a product carries its
definition, so the proxies must pickle.

A proxy is reduced to a proxy over a copy of the mapping it shows, which is
all a read-only view promises.  The reduction is registered with
:mod:`copyreg`, so it applies to every pickler in the process: Python
refuses such proxies only because one may show a class namespace, which is
never pickled by value anyway.
"""

from __future__ import annotations

import copyreg
from collections.abc import Callable
from types import MappingProxyType
from typing import Any


def _mapping_proxy(mapping: dict[Any, Any]) -> MappingProxyType[Any, Any]:
    # The type itself cannot be pickled by reference: it is not reachable
    # under its name ``mappingproxy``.
    return MappingProxyType(mapping)


def _reduce_mapping_proxy(
    proxy: MappingProxyType[Any, Any],
) -> tuple[Callable[[dict[Any, Any]], MappingProxyType[Any, Any]], tuple[dict[Any, Any]]]:
    return _mapping_proxy, (dict(proxy),)


def install_mapping_proxy_pickle() -> None:
    """Register the reduction; calling it again changes nothing."""

    copyreg.pickle(MappingProxyType, _reduce_mapping_proxy)


__all__ = ["install_mapping_proxy_pickle"]
