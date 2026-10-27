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

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..artifacts.assembly_io import attached_definition
from ..product.packages import build_product_package, encode_product_package
from ..scene.preview import PreviewScene, compile_preview, encode_preview, entity_info
from ._marimo import safe_get_context
from .cells import NotebookCells
from .config import read_notebook_config
from .executor import finish_kernel_cache
from .projection import find_product, project_product

PACKAGE_MEDIA_TYPE = "application/vnd.simplecad.scadpkg"
PREVIEW_MEDIA_TYPE = "application/vnd.simplecad.preview"


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
    finish_kernel_cache(config)  # the product is modified below: let the cache finish pickling it
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


_last_preview: PreviewScene | None = None
"""The scene last previewed in this kernel: what :func:`preview_entity_info` answers about."""

last_timings: dict[str, float] = {}
"""Milliseconds the last :func:`live_preview` / :func:`publish_preview` spent: ``compile_ms``, ``encode_ms``, ``post_ms``."""


def _live_scene() -> PreviewScene:
    """The preview scene of the running notebook's product (not yet encoded)."""

    global _last_preview
    started = time.perf_counter()
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
    values = {name: glbls[name] for cell in ordered for name in cell.defs if name in glbls}
    read = frozenset().union(*(cell.refs for cell in ordered))
    scene = compile_preview(find_product(config, values, read))
    last_timings["compile_ms"] = round((time.perf_counter() - started) * 1000, 1)
    _last_preview = scene
    return scene


def live_preview() -> tuple[bytes, PreviewScene]:
    """The preview of the running notebook's product, from the values in the kernel.

    Unlike :func:`live_package` this does not project the product onto a
    definition: it looks at the solids as they are, which takes a fraction of the
    time (see :mod:`simplecadapi.scene.preview`).
    """

    scene = _live_scene()
    encoded = time.perf_counter()
    data = encode_preview(scene)
    last_timings["encode_ms"] = round((time.perf_counter() - encoded) * 1000, 1)
    return data, scene


_posted: set[str] = set()
"""The part keys of the preview this kernel last posted: the server holds them (it keeps the parts of its latest model)."""


def _post(url: str, data: bytes, step: str, delta: bool, timeout: float) -> None:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": PREVIEW_MEDIA_TYPE, "X-Live-Step": step, "X-Preview-Delta": "1" if delta else "0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def publish_preview(url: str, *, step: str = "", timeout: float = 60.0) -> dict[str, Any]:
    """:func:`live_preview`, then POST it to *url*; returns a short summary.

    Only the parts the server does not hold are sent: it keeps the parts of the model it was last given, so after a
    joint angle changed nothing but the nodes travel.  When the server answers that it lacks a part (it was given
    another model meanwhile) the whole preview is sent.
    """

    global _posted
    scene = _live_scene()
    omit = _posted & scene.parts.keys()
    encoded = time.perf_counter()
    data = encode_preview(scene, omit)
    last_timings["encode_ms"] = round((time.perf_counter() - encoded) * 1000, 1)
    posted = time.perf_counter()
    try:
        try:
            _post(url, data, step, bool(omit), timeout)
        except urllib.error.HTTPError as error:
            if error.code != 409:
                raise
            data = encode_preview(scene)  # the server lacks parts: send it all
            _post(url, data, step, False, timeout)
    except (urllib.error.URLError, OSError) as error:
        _posted = set()
        raise RuntimeError(f"publishing the preview to {url} failed: {error}") from error
    _posted = set(scene.parts)
    last_timings["post_ms"] = round((time.perf_counter() - posted) * 1000, 1)
    return {"nodes": len(scene.nodes), "parts": len(scene.parts), "bytes": len(data), **last_timings}


def preview_entity_info(entity_id: str) -> dict[str, Any] | None:
    """The properties of one entity of the scene last previewed (see :func:`entity_info`)."""

    if _last_preview is None:
        return None
    return entity_info(_last_preview, entity_id)


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


__all__ = [
    "LivePackage",
    "LiveUnavailableError",
    "live_package",
    "live_preview",
    "preview_entity_info",
    "publish_live",
    "publish_preview",
]
