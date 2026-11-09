"""A failing step: the preview shows the model before it, and says so.

When a cell fails, the product is not made; the editor's preview is then of what
the cells before it made (the body the failing feature was applied to), flagged
partial with the failing cell, instead of the last model that built.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import simplecadapi as scad
from simplecadapi.runtime.config import read_notebook_config
from simplecadapi.runtime.live import FailedCell, preview_product
from simplecadapi.runtime.projection import NoProductYetError, ProductNotFoundError

NOTEBOOK = '''# /// script
# [tool.simplecadapi]
# kind = "part"
# id = "plate"
# ///
import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- params ----
    SIZE = scad.var("size", 40.0, comment="Size", unit="mm")  # ui: slider(10, 80, step=1, label="Size")
    FILLET = scad.var("fillet", 2.0, comment="Fillet", unit="mm")  # ui: slider(0.5, 40, step=0.5, label="Fillet")
    return FILLET, SIZE


@app.cell
def _(SIZE):
    # ---- feature: base (build) ----
    base = scad.make_box_rsolid(SIZE, SIZE, 10.0)
    return (base,)


@app.cell
def _(base):
    # ---- feature: bore (subtract) ----
    _tool = scad.make_cylinder_rsolid(radius=5.0, height=40.0, bottom_face_center=(0.0, 0.0, -10.0), axis=(0.0, 0.0, 1.0))
    bore = scad.cut_rsolid(base, _tool)
    return (bore,)


@app.cell
def _(FILLET, bore):
    # ---- feature: rounded (modify) ----
    rounded = scad.fillet_rsolid(bore, scad.ql.edges().resolve(bore), FILLET)
    return (rounded,)


@app.cell
def _(rounded):
    # ---- feature: top (subtract) ----
    _pin = scad.make_cylinder_rsolid(radius=2.0, height=40.0, bottom_face_center=(12.0, 12.0, -10.0), axis=(0.0, 0.0, 1.0))
    top = scad.cut_rsolid(rounded, _pin)
    return (top,)


if __name__ == "__main__":
    app.run()
'''


def _cell(defs, refs=()):
    return SimpleNamespace(defs=set(defs), refs=set(refs))


ROUNDED = FailedCell("r1", "rounded", "exception", "SimpleCADError: fillet_rsolid: too large")


def test_the_body_the_failing_feature_was_applied_to_is_previewed_and_flagged(tmp_path):
    path = tmp_path / "plate.py"
    path.write_text(NOTEBOOK)
    config = read_notebook_config(path)
    with scad.GraphSession(graph_id="partial-unit"):
        base = scad.make_box_rsolid(40.0, 40.0, 10.0)
        bore = scad.cut_rsolid(base, scad.make_cylinder_rsolid(radius=5.0, height=40.0, bottom_face_center=(0.0, 0.0, -10.0)))
    cells = [_cell({"SIZE"}), _cell({"base"}, {"SIZE"}), _cell({"bore"}, {"base"})]
    values = {"SIZE": 40.0, "base": base, "bore": bore}
    # the cells that are left: whole, as before
    product, partial = preview_product(config, cells, values)
    assert partial is None and product.part_id == "plate"
    # rounded (reads bore) failed and top did not run: bore is the open body, and the preview says why
    product, partial = preview_product(
        config, cells, values, failed=[ROUNDED], skipped=["t1"], lost_reads=frozenset({"bore", "FILLET", "rounded"})
    )
    assert abs(product.body.get_volume() - bore.get_volume()) < 1e-6
    assert partial == {"failed": [ROUNDED.to_dict()], "skipped": ["t1"], "shown": ["bore"]}
    # nothing before the failing step makes a model: an error that names the step
    with pytest.raises(ProductNotFoundError, match="rounded failed"):
        preview_product(config, [_cell({"SIZE"})], {"SIZE": 40.0}, failed=[ROUNDED])


def test_a_notebook_with_no_solid_yet_has_no_product_and_that_is_no_fault(tmp_path):
    path = tmp_path / "plate.py"
    path.write_text(NOTEBOOK)
    config = read_notebook_config(path)
    # only numbers so far (a sketch or a curve is no solid either): no product, said apart from a wrong one
    with pytest.raises(NoProductYetError, match="no Part, Assembly or solid yet"):
        preview_product(config, [_cell({"SIZE"})], {"SIZE": 40.0})
    with scad.GraphSession(graph_id="partial-other"):
        other = scad.Part(part_id="other", body=scad.make_box_rsolid(1.0, 1.0, 1.0))
    with pytest.raises(ProductNotFoundError, match="other") as raised:
        preview_product(config, [_cell({"other"})], {"other": other})
    assert not isinstance(raised.value, NoProductYetError)


def test_an_explicit_product_no_failed_cell_builds_on_is_whole(tmp_path):
    path = tmp_path / "plate.py"
    path.write_text(NOTEBOOK)
    config = read_notebook_config(path)
    with scad.GraphSession(graph_id="partial-explicit"):
        body = scad.make_box_rsolid(10.0, 10.0, 10.0)
        part = scad.Part(part_id="plate", body=body)
    cells = [_cell({"body"}), _cell({"part"}, {"body"})]
    values = {"body": body, "part": part}
    probe = FailedCell("p1", "probe", "exception", "ValueError: x")
    product, partial = preview_product(config, cells, values, failed=[probe], lost_reads=frozenset({"body"}))
    assert product is part and partial is None
    # a failed cell that would have built on the product: the product shown is the one before it
    product, partial = preview_product(config, cells, values, failed=[probe], lost_reads=frozenset({"part"}))
    assert product is part and partial is not None and partial["shown"] == ["part"]


def _wait(predicate, timeout=90.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.3)
    return False


def test_the_editor_previews_the_model_before_a_failing_parameter_change(tmp_path):
    pytest.importorskip("uvicorn")
    import uvicorn

    from simplecadapi.editor.server import WorkspaceState, create_app

    root = tmp_path.resolve()
    path = root / "plate.py"
    path.write_text(NOTEBOOK)
    state = WorkspaceState(root)
    state.port = 17753
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=state.port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    state.hub.attach_loop(asyncio.new_event_loop())
    sent: list[dict] = []
    emit = state.emit
    state.emit = lambda envelope: (sent.append(envelope), emit(envelope))[1]  # type: ignore[method-assign]
    try:
        state.start_kernel(path)
        whole = state.latest_preview_bytes
        assert whole and state.partial is None
        # a fillet too large for the plate: the preview is the bored plate, flagged with the failing step
        state.dispatch_command({"type": "param.set", "values": {"FILLET": 20}})
        assert _wait(lambda: state.partial is not None), state._last_publish_error
        failed = state.partial["failed"]
        assert [cell["name"] for cell in failed] == ["rounded"] and failed[0]["status"] == "exception"
        assert "fillet_rsolid" in failed[0]["error"]
        assert state.partial["shown"] == ["bore"] and len(state.partial["skipped"]) == 1
        assert state.latest_preview_bytes != whole
        assert state.snapshot()["partial"] == state.partial
        last = [envelope for envelope in sent if envelope.get("type") == "preview"][-1]
        assert last["partial"] == state.partial and not state._last_publish_error
        # fixed: the whole model replaces it
        state.dispatch_command({"type": "param.set", "values": {"FILLET": 2.5}})
        assert _wait(lambda: state.partial is None)
        last = [envelope for envelope in sent if envelope.get("type") == "preview"][-1]
        assert last["partial"] is None and state.snapshot()["partial"] is None
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True
