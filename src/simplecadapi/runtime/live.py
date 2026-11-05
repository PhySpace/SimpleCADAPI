"""The product of a notebook running in an editor's marimo kernel.

Headless, :func:`~.runner.run_notebook` runs the cells and projects the
product.  In the editor marimo runs them, reactively, and keeps their
values in the kernel; :func:`live_package` projects the product from
those.  Same executor, same projection, same package: a notebook gives the
same product wherever it runs.

The editor's bridge calls :func:`publish_live` from a snippet it executes
in the kernel once the cells have settled.

A cell that fails leaves no values, and the cells after it that read them do
not run: the product is not made.  The preview then shows what the notebook
does have, the model as it is before the failing step, and says so
(:func:`preview_product`): a changed parameter that breaks a feature shows the
body that feature was applied to, not the last model that built.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from collections.abc import Iterable, Mapping, Set as AbstractSet
from typing import Any

from ..artifacts.assembly_io import attached_definition
from ..product.packages import build_product_package, encode_product_package
from ..scene.preview import PreviewScene, compile_preview, encode_preview, entity_info, refine_preview
from ._marimo import safe_get_context
from .cells import NotebookCells
from .config import NotebookConfig, read_notebook_config
from .executor import finish_kernel_cache
from .projection import NoProductYetError, Product, ProductNotFoundError, find_product, open_bodies, product_reads, project_product
from .workspace import features_in_cell

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
    cell has produced the product yet, or a cell it is built from failed.  ``validate``
    runs the package's full contract validation; the live path skips it.
    """

    scope = live_scope()
    config = scope.config
    finish_kernel_cache(config)  # the product is modified below: let the cache finish pickling it
    found, partial = preview_product(
        config, scope.cells, scope.values, failed=scope.failed, skipped=scope.skipped, lost_reads=scope.lost_reads
    )
    if partial is not None:
        # a package is the whole product: the model before a failing step is only previewed
        first = scope.failed[0]
        raise ProductNotFoundError(
            f"{config.path.name}: {first.name} failed ({first.error or first.status}); fix it to make the product"
        )
    product = project_product(
        found,
        config=config,
        cells=NotebookCells(config.path, list(scope.ordered)),
        values=scope.values.values(),
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


_FAILED = frozenset({"exception", "interrupted", "marimo-error"})
"""The marimo run states of a cell that did not finish: it raised, was stopped, or could not run (a syntax error, a name
defined twice)."""


@dataclass(frozen=True)
class FailedCell:
    """A cell of the notebook that did not finish, as a preview reports it."""

    cell_id: str
    name: str
    """The feature the cell makes (its ``# ---- feature:`` header), else the cell's name, else what it defines."""
    status: str
    """marimo's run state: ``exception``, ``interrupted`` or ``marimo-error``."""
    error: str
    """``Type: message`` (cut short), empty when marimo kept no exception."""

    def to_dict(self) -> dict[str, str]:
        return {"cell": self.cell_id, "name": self.name, "status": self.status, "error": self.error}


@dataclass(frozen=True)
class LiveScope:
    """The values of the running notebook that a preview can be made from.

    The cells that failed, and every cell downstream of one, are left out: in lazy mode marimo does not clear the values a
    blocked descendant made in an earlier run, and a failed cell may have bound some names before it raised.
    """

    config: NotebookConfig
    cells: list[Any]
    """The marimo cells that are left (not failed, not downstream of a failed cell)."""
    values: dict[str, object]
    """Their top-level values."""
    failed: tuple[FailedCell, ...] = ()
    """The cells that failed and are downstream of no other failed cell (the failing steps), in notebook order."""
    skipped: tuple[str, ...] = ()
    """The ids of the cells left out because a cell upstream of them failed."""
    lost_reads: frozenset[str] = frozenset()
    """The names the failed and skipped cells read: what they would have built on."""
    ordered: tuple[Any, ...] = ()
    """Every marimo cell of the notebook (the source positions of a projection are looked up in all of them)."""


def _cell_name(cell: Any) -> str:
    found = features_in_cell(getattr(cell, "code", "") or "")
    if found:
        return found[0].slug
    name = getattr(cell, "name", "") or ""
    if name and name != "_":
        return name
    defs = sorted(name for name in getattr(cell, "defs", ()) if not name.startswith("_"))
    return ", ".join(defs) if defs else f"cell {cell.cell_id}"


def _cell_error(cell: Any) -> str:
    """``Type: message`` of the exception a failed cell raised, short: an SDK error by its operation and what happened."""

    error = getattr(cell, "exception", None)
    if error is None:
        return ""
    text = ""
    try:
        details = error.to_dict() if callable(getattr(error, "to_dict", None)) else None
    except Exception:  # noqa: BLE001 - the message is a courtesy, never a second failure
        details = None
    if isinstance(details, dict) and details.get("what_happened"):
        operation = details.get("operation") or getattr(error, "operation", "")
        text = f"{operation}: {details['what_happened']}" if operation else str(details["what_happened"])
    else:
        text = next((line.strip() for line in str(error).splitlines() if line.strip()), "")
    text = " ".join(text.split())
    return f"{type(error).__name__}: {text}"[:400] if text else type(error).__name__


def live_scope() -> LiveScope:
    """The values the running notebook's cells hold, without the failed cells and those downstream of them.

    Call from inside the marimo kernel; raises :class:`LiveUnavailableError` outside one.
    """

    context = safe_get_context()
    if context is None or context.filename is None:
        raise LiveUnavailableError("not running inside a marimo kernel")
    config = read_notebook_config(context.filename)
    if config is None:
        raise LiveUnavailableError(
            f"{context.filename}: not a SimpleCAD notebook (no [tool.simplecadapi])"
        )
    graph = context.graph
    ordered = list(graph.cells.values())
    failed = [cell for cell in ordered if getattr(cell, "run_result_status", None) in _FAILED]
    lost: set[str] = set()
    for cell in failed:
        lost |= graph.descendants(cell.cell_id)
    roots = [cell for cell in failed if cell.cell_id not in lost]
    failed_ids = {cell.cell_id for cell in failed}
    lost |= failed_ids
    kept = [cell for cell in ordered if cell.cell_id not in lost]
    glbls = context.globals
    return LiveScope(
        config=config,
        cells=kept,
        values={name: glbls[name] for cell in kept for name in cell.defs if name in glbls},
        failed=tuple(
            FailedCell(cell.cell_id, _cell_name(cell), str(cell.run_result_status), _cell_error(cell)) for cell in roots
        ),
        skipped=tuple(cell.cell_id for cell in ordered if cell.cell_id in lost and cell.cell_id not in failed_ids),
        lost_reads=frozenset(name for cell in ordered if cell.cell_id in lost for name in cell.refs),
        ordered=tuple(ordered),
    )


def preview_product(
    config: NotebookConfig,
    cells: Iterable[Any],
    values: Mapping[str, object],
    *,
    failed: Iterable[FailedCell] = (),
    skipped: Iterable[str] = (),
    lost_reads: AbstractSet[str] = frozenset(),
) -> tuple[Product, dict[str, Any] | None]:
    """The product to preview from *values* (the cells that are left, see :class:`LiveScope`), and whether it is partial.

    With no failed cell this is :func:`~.projection.find_product`.  With one, the product is found the same way among the
    values that are left, the cells read by the failed and skipped cells no longer counting: a part notebook's open bodies
    are then the bodies the failing feature was applied to, an assembly built up over cells is the assembly before the
    failing step.  The second item says what is shown (``None`` when the product is whole): ``{"failed": [...], "skipped":
    [cell ids], "shown": [names]}``.  A product no failed cell would have built on (an explicit product upstream of none of
    them) is whole.  Raises :class:`~.projection.ProductNotFoundError` when nothing is left to show, naming the failed cell.
    """

    failed = tuple(failed)
    cells = list(cells)
    read = product_reads(cells, values)
    try:
        product = find_product(config, values, read)
    except ProductNotFoundError as error:
        if not failed:
            raise
        first = failed[0]
        raise ProductNotFoundError(
            f"{config.path.name}: {first.name} failed ({first.error or first.status}); the cells before it make no model"
        ) from error
    if not failed:
        return product, None
    names = [name for name, value in values.items() if value is product or getattr(value, "value", None) is product]
    if names and not set(names) & lost_reads:
        return product, None
    return product, {
        "failed": [cell.to_dict() for cell in failed],
        "skipped": list(skipped),
        "shown": names or open_bodies(values, read),
    }


_last_partial: dict[str, Any] | None = None
"""What :func:`preview_product` said of the scene last previewed: ``None`` when it is the whole product."""


def _live_scene() -> PreviewScene:
    """The preview scene of the running notebook's product (not yet encoded); partial when a cell failed."""

    global _last_preview, _last_partial
    started = time.perf_counter()
    scope = live_scope()
    try:
        product, partial = preview_product(
            scope.config,
            scope.cells,
            scope.values,
            failed=scope.failed,
            skipped=scope.skipped,
            lost_reads=scope.lost_reads,
        )
    except NoProductYetError:
        # no solid yet (only sketches, curves, workplanes): the model is empty, which is no fault
        product, partial = None, None
    scene = compile_preview(product) if product is not None else PreviewScene(parts={}, nodes=[], solids={}, definitions={})
    last_timings["compile_ms"] = round((time.perf_counter() - started) * 1000, 1)
    _last_preview, _last_partial = scene, partial
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
    headers = {"Content-Type": PREVIEW_MEDIA_TYPE, "X-Live-Step": step, "X-Preview-Delta": "1" if delta else "0"}
    if _last_partial is not None:
        # the scene is the model before a failing step: the server tells the pages with the model itself (ASCII JSON)
        headers["X-Preview-Partial"] = json.dumps(_last_partial)
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def _server_words(error: urllib.error.HTTPError) -> str:
    """What the editor server said about a refused post (its JSON ``error``), else the HTTP status line."""

    try:
        said = json.loads(error.read()).get("error")
    except (OSError, ValueError, AttributeError):
        said = None
    return f"HTTP {error.code}: {said}" if said else str(error)


def publish_preview(url: str, *, step: str = "", timeout: float = 60.0) -> dict[str, Any]:
    """:func:`live_preview`, then POST it to *url*; returns a short summary.

    When a cell failed the preview is of the model before it (see :func:`preview_product`): the post says so (its
    ``X-Preview-Partial`` header) and so does the summary (``partial``).  Only the parts the server does not hold are sent: it keeps the parts of the model it was last given, so after a
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
                raise RuntimeError(f"publishing the preview to {url} failed: {_server_words(error)}") from error
            data = encode_preview(scene)  # the server lacks parts: send it all
            _post(url, data, step, False, timeout)
    except (urllib.error.URLError, OSError) as error:
        _posted = set()
        raise RuntimeError(f"publishing the preview to {url} failed: {error}") from error
    _posted = set(scene.parts)
    last_timings["post_ms"] = round((time.perf_counter() - posted) * 1000, 1)
    return {"nodes": len(scene.nodes), "parts": len(scene.parts), "bytes": len(data), **last_timings, "partial": _last_partial}


def workplane_frames(values: dict[str, Any]) -> list[dict[str, Any]]:
    """The workplanes among *values*: ``{name, origin, x_axis, y_axis, normal}`` per variable, in world coordinates.

    The frames are the SDK's own (``SimpleWorkplane.origin`` ...), as the kernel computed them: an editor draws and
    sketches on them without recomputing any geometry.
    """

    from .._cpp import SimpleWorkplane

    out: list[dict[str, Any]] = []
    for name, value in values.items():
        if isinstance(value, SimpleWorkplane):
            out.append(
                {
                    "name": name,
                    "origin": [float(v) for v in value.origin],
                    "x_axis": [float(v) for v in value.x_dir],
                    "y_axis": [float(v) for v in value.y_dir],
                    "normal": [float(v) for v in value.normal],
                }
            )
    return out


def live_workplanes() -> list[dict[str, Any]]:
    """The workplane variables of the running notebook (see :func:`workplane_frames`); empty outside a kernel."""

    context = safe_get_context()
    if context is None:
        return []
    glbls = context.globals
    values = {name: glbls[name] for cell in context.graph.cells.values() for name in cell.defs if name in glbls}
    return workplane_frames(values)


def scene_tag_splits(scene: PreviewScene) -> list[dict[str, Any]]:
    """The tag splits behind the solids of *scene*, with the entities of each piece (``scad.list_tag_splits``).

    One row per split: ``tag``, ``into`` (the pieces' tags), ``op``, and ``pieces``: per entity that carries a piece's
    tag, ``piece`` (its index in ``into``), ``node_id`` (the scene node drawing it) and ``entity_id``.  The editor
    highlights the pieces and says what was split, so whoever looks can judge whether the split was meant.
    """

    from .._cpp import list_tag_splits, ql

    rows: dict[tuple, dict[str, Any]] = {}
    for key, solid in scene.solids.items():
        try:
            splits = list_tag_splits(solid)
        except Exception:  # noqa: BLE001 - a diagnostic never breaks the preview
            continue
        if not splits:
            continue
        definition, body = scene.definitions[key], scene.bodies.get(key)
        prefix = f"entity/{definition}/" if body is None else f"entity/{definition}/body:{body}/"
        nodes = [node.node_id for node in scene.nodes if node.part_key == key]
        entities = [("solid", solid)] + [("face", f) for f in ql.faces().resolve(solid)] + [
            ("edge", e) for e in ql.edges().resolve(solid)
        ]
        tagged = [(kind, entity, set(entity._list_tags())) for kind, entity in entities]
        for split in splits:
            row = rows.setdefault(
                (split["node_id"], split["tag"], split["source_topo_id"]),
                {"tag": split["tag"], "into": list(split["into"]), "op": split["op"], "pieces": []},
            )
            for index, name in enumerate(split["into"]):
                for kind, entity, tags in tagged:
                    if name in tags:
                        for node_id in nodes:
                            row["pieces"].append(
                                {"piece": index, "node_id": node_id, "entity_id": f"{prefix}{kind}/{entity.topo_id}"}
                            )
    return list(rows.values())


def live_tag_splits() -> list[dict[str, Any]]:
    """:func:`scene_tag_splits` of the scene last previewed in this kernel (empty before the first preview)."""

    return scene_tag_splits(_last_preview) if _last_preview is not None else []


def preview_entity_info(entity_id: str) -> dict[str, Any] | None:
    """The properties of one entity of the scene last previewed (see :func:`entity_info`)."""

    if _last_preview is None:
        return None
    return entity_info(_last_preview, entity_id)


def preview_refined(keys: list[str], linear_tolerance: float, angular_tolerance: float, path: str) -> int:
    """:func:`refine_preview` of the scene last previewed, written to *path* (the editor's server reads it and hands it to
    the page that asked); the number of parts written.  Before the first preview nothing is written and 0 returned."""

    if _last_preview is None:
        return 0
    data = refine_preview(_last_preview, keys, linear_tolerance=linear_tolerance, angular_tolerance=angular_tolerance)
    with open(path, "wb") as handle:
        handle.write(data)
    return len([key for key in keys if key in _last_preview.solids])


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
    "FailedCell",
    "LiveScope",
    "live_scope",
    "preview_product",
    "live_tag_splits",
    "live_workplanes",
    "scene_tag_splits",
    "workplane_frames",
    "LivePackage",
    "LiveUnavailableError",
    "live_package",
    "live_preview",
    "preview_entity_info",
    "preview_refined",
    "publish_live",
    "publish_preview",
]
