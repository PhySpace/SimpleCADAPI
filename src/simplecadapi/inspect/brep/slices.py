"""Physical occupancy slices and target/candidate XOR diagnostics."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

import numpy as np
from simplecadapi._cpp.occt.BRepClass3d import BRepClass3d_SolidClassifier
from simplecadapi._cpp.occt.TopAbs import TopAbs_IN, TopAbs_ON
from simplecadapi._cpp.occt.TopoDS import TopoDS_Shape
from simplecadapi._cpp.occt.gp import gp_Pnt

from .inspect import inspect_shape_rbrepinspection
from .io import load_step_rshape

SlicePlane = Literal["xy", "xz", "yz"]


@dataclass(frozen=True)
class SliceSpec:
    """One constant-coordinate physical slice."""

    plane: SlicePlane
    value: float
    label: str | None = None

    @property
    def display_label(self) -> str:
        if self.label:
            return self.label
        constant = {"xy": "Z", "xz": "Y", "yz": "X"}[self.plane]
        return f"{constant}={self.value:g}"


@dataclass(frozen=True)
class SlicePanelResult:
    slice: str
    samples: int
    xor_samples: int


@dataclass(frozen=True)
class SliceComparison:
    target: str | None
    candidate: str | None
    total_samples: int
    xor_samples: int
    sampled_slices_identical: bool
    panels: tuple[SlicePanelResult, ...]
    image: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: str | Path, *, indent: int = 2) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=indent), encoding="utf-8")
        return output


def make_center_slice_specs_rslicespeclist(
    minimum: np.ndarray, maximum: np.ndarray
) -> tuple[SliceSpec, ...]:
    """Return one center slice normal to each global axis."""
    center = (np.asarray(minimum, dtype=float) + np.asarray(maximum, dtype=float)) / 2.0
    return (
        SliceSpec("yz", float(center[0]), f"X={center[0]:g}"),
        SliceSpec("xz", float(center[1]), f"Y={center[1]:g}"),
        SliceSpec("xy", float(center[2]), f"Z={center[2]:g}"),
    )


def _classifier(shape: TopoDS_Shape) -> BRepClass3d_SolidClassifier:
    classifier = BRepClass3d_SolidClassifier()
    classifier.Load(shape)
    return classifier


def _occupied(
    classifier: BRepClass3d_SolidClassifier,
    x: float,
    y: float,
    z: float,
    tolerance: float,
) -> bool:
    classifier.Perform(gp_Pnt(float(x), float(y), float(z)), tolerance)
    return classifier.State() in (TopAbs_IN, TopAbs_ON)


def _axis_ranges(target: TopoDS_Shape, candidate: TopoDS_Shape, margin_ratio: float):
    target_box = inspect_shape_rbrepinspection(target).bounding_box
    candidate_box = inspect_shape_rbrepinspection(candidate).bounding_box
    minimum = np.minimum(np.asarray(target_box[:3]), np.asarray(candidate_box[:3]))
    maximum = np.maximum(np.asarray(target_box[3:]), np.asarray(candidate_box[3:]))
    span = np.maximum(maximum - minimum, 1.0e-9)
    margin = span * margin_ratio
    return minimum - margin, maximum + margin


def _plane_axes(spec: SliceSpec) -> tuple[int, int, int]:
    # Return horizontal, vertical, constant XYZ indices.
    return {"xy": (0, 1, 2), "xz": (0, 2, 1), "yz": (1, 2, 0)}[spec.plane]


def compare_shape_slices_rslicecomparison(
    target: TopoDS_Shape,
    candidate: TopoDS_Shape,
    *,
    slices: Sequence[SliceSpec] | None = None,
    samples: tuple[int, int] = (91, 121),
    classification_tolerance: float = 1.0e-8,
    margin_ratio: float = 0.03,
    output_path: str | Path | None = None,
    target_name: str | None = None,
    candidate_name: str | None = None,
    dpi: int = 180,
) -> SliceComparison:
    """Compare occupancy on physical slices and optionally render an XOR image.

    This is a visual diagnostic, not a replacement for bidirectional Boolean
    comparison. Keep sample counts moderate because exact BREP classification
    is intentionally used for every point.
    """
    target_classifier = _classifier(target)
    candidate_classifier = _classifier(candidate)
    minimum, maximum = _axis_ranges(target, candidate, margin_ratio)
    selected_slices = (
        tuple(slices) if slices is not None else make_center_slice_specs_rslicespeclist(minimum, maximum)
    )
    if not selected_slices:
        raise ValueError("At least one physical slice is required")
    panel_data: list[tuple[SliceSpec, np.ndarray, np.ndarray, np.ndarray]] = []
    panel_results: list[SlicePanelResult] = []
    total_samples = 0
    xor_samples = 0

    for spec in selected_slices:
        horizontal_axis, vertical_axis, constant_axis = _plane_axes(spec)
        horizontal = np.linspace(
            minimum[horizontal_axis], maximum[horizontal_axis], samples[0]
        )
        vertical = np.linspace(
            minimum[vertical_axis], maximum[vertical_axis], samples[1]
        )
        horizontal_grid, vertical_grid = np.meshgrid(horizontal, vertical)
        code = np.zeros(horizontal_grid.shape, dtype=np.uint8)
        for row in range(horizontal_grid.shape[0]):
            for column in range(horizontal_grid.shape[1]):
                point = [0.0, 0.0, 0.0]
                point[horizontal_axis] = horizontal_grid[row, column]
                point[vertical_axis] = vertical_grid[row, column]
                point[constant_axis] = spec.value
                target_inside = _occupied(
                    target_classifier, *point, classification_tolerance
                )
                candidate_inside = _occupied(
                    candidate_classifier, *point, classification_tolerance
                )
                code[row, column] = (1 if target_inside else 0) + (
                    2 if candidate_inside else 0
                )
        mismatches = int(np.count_nonzero((code == 1) | (code == 2)))
        count = int(code.size)
        total_samples += count
        xor_samples += mismatches
        panel_results.append(SlicePanelResult(spec.display_label, count, mismatches))
        panel_data.append((spec, horizontal_grid, vertical_grid, code))

    rendered_path: str | None = None
    if output_path is not None:
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from matplotlib.colors import ListedColormap
        except ImportError as error:
            raise ImportError("Slice overlay rendering requires matplotlib") from error

        columns = 3
        rows = (len(panel_data) + columns - 1) // columns
        figure, axes = plt.subplots(
            rows, columns, figsize=(18, 5 * rows), constrained_layout=True
        )
        axes_array = np.atleast_1d(axes).ravel()
        color_map = ListedColormap(["white", "#e63946", "#ff9f1c", "#457b9d"])
        axis_labels = {"xy": ("X", "Y"), "xz": ("X", "Z"), "yz": ("Y", "Z")}
        for axes_item, (spec, horizontal_grid, vertical_grid, code), result in zip(
            axes_array, panel_data, panel_results
        ):
            axes_item.pcolormesh(
                horizontal_grid,
                vertical_grid,
                code,
                cmap=color_map,
                vmin=0,
                vmax=3,
                shading="nearest",
            )
            axes_item.set_title(
                f"{spec.display_label} - XOR samples {result.xor_samples}"
            )
            horizontal_label, vertical_label = axis_labels[spec.plane]
            axes_item.set_xlabel(horizontal_label)
            axes_item.set_ylabel(vertical_label)
            axes_item.set_aspect("equal")
        for axes_item in axes_array[len(panel_data) :]:
            axes_item.set_visible(False)
        figure.suptitle(
            "BREP slice overlay: blue=both, red=target only, orange=candidate only"
        )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output, dpi=dpi)
        plt.close(figure)
        rendered_path = str(output)

    return SliceComparison(
        target=target_name,
        candidate=candidate_name,
        total_samples=total_samples,
        xor_samples=xor_samples,
        sampled_slices_identical=xor_samples == 0,
        panels=tuple(panel_results),
        image=rendered_path,
    )


def compare_step_slices_rslicecomparison(
    target_path: str | Path,
    candidate_path: str | Path,
    **kwargs,
) -> SliceComparison:
    """Load two STEP solids and compare physical occupancy slices."""
    target_source = Path(target_path)
    candidate_source = Path(candidate_path)
    return compare_shape_slices_rslicecomparison(
        load_step_rshape(target_source),
        load_step_rshape(candidate_source),
        target_name=str(target_source),
        candidate_name=str(candidate_source),
        **kwargs,
    )
