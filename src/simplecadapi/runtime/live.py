"""The product of a notebook running in an editor's marimo kernel.

Headless, :func:`~.runner.run_notebook` runs the cells and projects the
product.  In the editor marimo runs them, reactively, and keeps their
values in the kernel; :func:`live_package` projects the product from
those.  Same executor, same projection, same package: a notebook gives the
same product wherever it runs.

The editor's bridge calls :func:`publish_live` from a snippet it executes
in the kernel once the cells have settled.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass

from ..artifacts.assembly_io import attached_definition
from ..product.packages import build_product_package, encode_product_package
from ._marimo import safe_get_context
from .cells import NotebookCells
from .config import read_notebook_config
from .projection import find_product, project_product

PACKAGE_MEDIA_TYPE = "application/vnd.simplecad.scadpkg"


class LiveUnavailableError(RuntimeError):
    """No SimpleCAD notebook is running in this kernel."""


@dataclass(frozen=True)
class LivePackage:
    data: bytes
    """The ``.scadpkg``."""
    definition_id: str
    definition_kind: str
    content_hash: str


def live_package(*, validate: bool = False) -> LivePackage:
    """Project the running notebook's product and package it.

    Call from inside the marimo kernel.  Raises :class:`LiveUnavailableError`
    outside one, and :class:`~.projection.ProductNotFoundError` while no
    cell has produced the product yet (or a cell failed).  ``validate``
    runs the package's full contract validation; the live path skips it.
    """

    context = safe_get_context()
    if context is None or context.filename is None:
        raise LiveUnavailableError("not running inside a marimo kernel")
    config = read_notebook_config(context.filename)
    if config is None:
        raise LiveUnavailableError(
            f"{context.filename}: not a SimpleCAD notebook (no [tool.simplecadapi])"
        )
    glbls = context.globals
    ordered = list(context.graph.cells.values())
    cells = NotebookCells(config.path, ordered)
    values = {
        name: glbls[name] for cell in ordered for name in cell.defs if name in glbls
    }
    read = frozenset().union(*(cell.refs for cell in ordered))
    product = project_product(
        find_product(config, values, read),
        config=config,
        cells=cells,
        values=values.values(),
    )
    definition = attached_definition(product)
    # project_product attaches one to every product it returns.
    assert definition is not None
    package = build_product_package(definition, validate=validate)
    return LivePackage(
        data=encode_product_package(package),
        definition_id=definition.definition_id,
        definition_kind=definition.definition_kind,
        content_hash=definition.content_hash,
    )


def publish_live(url: str, *, step: str = "", timeout: float = 60.0) -> LivePackage:
    """:func:`live_package`, then POST the package bytes to *url*."""

    package = live_package()
    request = urllib.request.Request(
        url,
        data=package.data,
        headers={"Content-Type": PACKAGE_MEDIA_TYPE, "X-Live-Step": step},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError(f"publishing the package to {url} failed: {error}") from error
    return package


__all__ = ["LivePackage", "LiveUnavailableError", "live_package", "publish_live"]
