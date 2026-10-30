"""The failure pictures, and what a refused preview post tells the person."""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path

import pytest

import simplecadapi as scad


@pytest.fixture(autouse=True)
def drawing(tmp_path, monkeypatch):
    from simplecadapi._cpp import evidence

    monkeypatch.delenv("SCA_NO_DIAGNOSTIC_RENDER", raising=False)
    monkeypatch.chdir(tmp_path)
    evidence._RENDER_DEDUP.clear()


def test_a_query_that_matches_nothing_still_draws_the_solid() -> None:
    """2.2.6 drew the plain solid when a face query matched nothing (the common ``exactly(1)`` found 0)."""
    box = scad.make_box_rsolid(10, 10, 10)
    with pytest.raises(scad.SimpleCADError) as raised:
        scad.ql.faces().where(scad.ql.surface_type("TORUS")).exactly(1).resolve(box)
    evidence = raised.value.to_dict()["evidence"]
    assert len(evidence) == 1 and evidence[0]["kind"] == "render"
    assert Path(evidence[0]["path"]).stat().st_size > 10_000


def test_a_picture_that_cannot_be_drawn_is_said_on_stderr(capsys, monkeypatch) -> None:
    from simplecadapi._cpp import evidence

    def broken(*args, **kwargs):
        raise RuntimeError("no plot")

    monkeypatch.setattr(evidence, "_wire_plan", broken)
    assert evidence.provide("wire_plan_render", "loft", "plan", "caption", "key", [], {}) is None
    assert "could not be drawn (RuntimeError: no plot)" in capsys.readouterr().err


def test_a_refused_preview_post_reports_what_the_server_said() -> None:
    from simplecadapi.runtime.live import _server_words

    refused = urllib.error.HTTPError("http://x", 400, "Bad Request", {}, io.BytesIO(b'{"ok": false, "error": "damaged preview: KeyError: key"}'))
    assert _server_words(refused) == "HTTP 400: damaged preview: KeyError: key"
    bare = urllib.error.HTTPError("http://x", 500, "Server Error", {}, io.BytesIO(b"<html>"))
    assert "500" in _server_words(bare)
