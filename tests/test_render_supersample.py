"""Regression tests for the supersampled screenshot writer (#32).

The writer must create its temp frame without holding a handle open while
vtkPNGWriter writes the same path (Windows denies the second open), and it
must not leak temp siblings when the render fails.
"""

from pathlib import Path

import pytest
from PIL import Image

from simplecadapi.inspect.brep import render as render_module


def test_supersampled_write_downsamples_and_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "box.png"

    def fake_write(window, path: Path) -> None:
        Image.new("RGB", (8, 8), (255, 0, 0)).save(path)

    monkeypatch.setattr(render_module, "_write_window", fake_write)
    render_module._write_window_supersampled(object(), output, 2)

    with Image.open(output) as img:
        assert img.size == (4, 4)
    assert list(tmp_path.glob(".box-ss*")) == []


def test_supersampled_write_cleans_up_on_render_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "box.png"

    def failing_write(window, path: Path) -> None:
        path.write_text("partial")  # simulate vtk writing before failing
        raise RuntimeError("vtk failure")

    monkeypatch.setattr(render_module, "_write_window", failing_write)
    with pytest.raises(RuntimeError):
        render_module._write_window_supersampled(object(), output, 2)

    # The old NamedTemporaryFile form leaked the temp sibling here.
    assert not output.exists()
    assert list(tmp_path.glob(".box-ss*")) == []
