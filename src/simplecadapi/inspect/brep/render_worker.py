"""One-shot VTK render worker for native crash isolation."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any, Mapping


def _read_polydata(path: Path):
    import vtk

    # VTK's own chatter (a missing X server, driver notes) reads as a render
    # failure; a real one fails the worker and is named by the caller.
    vtk.vtkObject.GlobalWarningDisplayOff()
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(path))
    reader.Update()
    output = vtk.vtkPolyData()
    output.DeepCopy(reader.GetOutput())
    return output


def _load_datasets(root: Path, values: Mapping[str, str | None]) -> dict[str, Any]:
    return {
        str(name): None if member is None else _read_polydata(root / str(member))
        for name, member in values.items()
    }


def _render_views(
    datasets: Mapping[str, Any], output_path: Path, options: Mapping[str, Any]
) -> None:
    from .render import _render_polydata_views_in_process

    surface_groups = [
        (
            datasets[str(item["dataset"])],
            tuple(item["color"]),
            float(item["opacity"]),
        )
        for item in options.get("surface_groups", [])
    ]
    edge_groups = [
        (datasets[str(item["dataset"])], tuple(item["color"]))
        for item in options.get("edge_groups", [])
    ]
    point_groups = [
        (datasets[str(item["dataset"])], tuple(item["color"]))
        for item in options.get("point_groups", [])
    ]
    legend = options.get("legend")
    callouts = options.get("callouts")
    _render_polydata_views_in_process(
        datasets.get("base"),
        output_path,
        title=str(options["title"]),
        views=tuple(tuple(item) for item in options["views"]),
        image_size=tuple(float(value) for value in options["image_size"]),
        dpi=int(options["dpi"]),
        context_opacity=float(options["context_opacity"]),
        highlight_edge_width=float(options["highlight_edge_width"]),
        highlight_point_size=float(options["highlight_point_size"]),
        brep_edge_polydata=datasets.get("brep_edges"),
        highlighted_polydata=datasets.get("highlighted"),
        highlighted_edge_polydata=datasets.get("highlighted_edges"),
        highlighted_point_polydata=datasets.get("highlighted_points"),
        highlighted_groups=surface_groups,
        highlighted_edge_groups=edge_groups,
        highlighted_point_groups=point_groups,
        legend=(
            tuple((str(label), tuple(color)) for label, color in legend)
            if legend is not None
            else None
        ),
        legend_columns=int(options["legend_columns"]),
        legend_panel=bool(options["legend_panel"]),
        show_axes=bool(options.get("show_axes", False)),
        datasets=datasets,
        edge_width_scale=float(options.get("edge_width_scale", 0.0019)),
        supersample=int(options.get("supersample", 1)),
        style=str(options.get("style", "standard")),
        zoom=None if options.get("zoom") is None else float(options["zoom"]),
        view_up=(
            None
            if options.get("view_up") is None
            else tuple(float(value) for value in options["view_up"])
        ),
        callouts=(
            [
                (
                    str(entry[0]),
                    tuple(float(value) for value in entry[1]),
                    tuple(entry[2]),
                    *([str(entry[3])] if len(entry) > 3 else []),
                )
                for entry in callouts
            ]
            if callouts is not None
            else None
        ),
    )



def _main(manifest_path: Path) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise ValueError("unsupported render worker schema")
    mode = str(payload.get("mode", ""))
    datasets = _load_datasets(manifest_path.parent, payload["datasets"])
    output_path = Path(payload["output_path"])
    options = payload["options"]
    lock_path = Path(
        os.environ.get(
            "SIMPLECAD_VTK_RENDER_LOCK", "/tmp/simplecad-vtk-render.lock"
        )
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if mode == "views":
            _render_views(datasets, output_path, options)
        else:
            raise ValueError(f"unsupported render worker mode: {mode}")
        Path(payload["completion_path"]).touch()
        # vtkCocoaRenderWindow can crash while Python unwinds VTK wrappers after
        # rendering. Exit before this frame is destroyed; the OS releases the
        # one-shot worker's native resources and file lock.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


if __name__ == "__main__":
    exit_code = 0
    try:
        if len(sys.argv) != 2:
            raise ValueError("usage: python -m simplecadapi.inspect.brep.render_worker MANIFEST")
        _main(Path(sys.argv[1]))
    except BaseException:
        traceback.print_exc()
        exit_code = 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
