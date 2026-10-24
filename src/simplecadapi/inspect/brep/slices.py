"""Physical occupancy slices and target/candidate XOR diagnostics."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

import numpy as np
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.TopAbs import TopAbs_IN, TopAbs_ON
from OCP.TopoDS import TopoDS_Shape
from OCP.gp import gp_Pnt

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


def render_sections_rpath(
    *,
    sections: Sequence[Mapping[str, Any]],
    output_path: str | Path,
    titles: Sequence[str] | None = None,
    columns: int = 3,
    image_size_per_panel: tuple[float, float] = (6.0, 5.0),
    dpi: int = 180,
) -> Path:
    """Render detailed section descriptors as a local-coordinate 2D atlas.

    ``sections`` must contain non-compact results from
    ``inspect_section_rdescriptor``. The renderer consumes each contour's
    existing ``samples_2d`` values and never recalculates or projects BREP
    geometry.

    Parameters
    ----------
    sections:
        Detailed section descriptors in the desired panel order.
    output_path:
        Destination image path. Missing parent directories are created.
    titles:
        Optional panel titles in the same order as ``sections``.
    columns:
        Positive number of atlas columns.
    image_size_per_panel:
        Positive panel width and height in inches.
    dpi:
        Positive output resolution in dots per inch.

    Returns
    -------
    Path
        The image path that was written.

    Raises
    ------
    ValueError
        If the atlas options are invalid, a compact descriptor is supplied,
        or contour coordinates are missing, malformed, or non-finite.
    """
    selected_sections = tuple(sections)
    if not selected_sections:
        raise ValueError("At least one section is required")
    if not isinstance(columns, int) or isinstance(columns, bool) or columns < 1:
        raise ValueError("columns must be a positive integer")
    if len(image_size_per_panel) != 2 or any(
        not np.isfinite(value) or value <= 0.0 for value in image_size_per_panel
    ):
        raise ValueError("image_size_per_panel must contain two positive finite values")
    if not isinstance(dpi, int) or isinstance(dpi, bool) or dpi < 1:
        raise ValueError("dpi must be a positive integer")
    selected_titles = tuple(titles) if titles is not None else None
    if selected_titles is not None and len(selected_titles) != len(selected_sections):
        raise ValueError("titles must contain exactly one entry per section")

    panel_contours: list[list[tuple[np.ndarray, bool, str, int]]] = []
    for section_index, section in enumerate(selected_sections):
        if not isinstance(section, Mapping):
            raise TypeError(f"sections[{section_index}] must be a mapping")
        if section.get("compact") is True:
            raise ValueError(
                f"sections[{section_index}] is compact; regenerate it with compact=False "
                "so contours include samples_2d"
            )
        contours = section.get("contours")
        if not isinstance(contours, Sequence) or isinstance(contours, (str, bytes)):
            raise ValueError(f"sections[{section_index}].contours must be a sequence")
        validated_contours: list[tuple[np.ndarray, bool, str, int]] = []
        for contour_index, contour in enumerate(contours):
            if not isinstance(contour, Mapping):
                raise TypeError(
                    f"sections[{section_index}].contours[{contour_index}] must be a mapping"
                )
            if "samples_2d" not in contour:
                raise ValueError(
                    f"sections[{section_index}].contours[{contour_index}] is missing "
                    "samples_2d; regenerate the section with compact=False"
                )
            try:
                points = np.asarray(contour["samples_2d"], dtype=float)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"sections[{section_index}].contours[{contour_index}].samples_2d "
                    "must contain numeric coordinates"
                ) from error
            if points.ndim != 2 or points.shape[1:] != (2,) or len(points) < 2:
                raise ValueError(
                    f"sections[{section_index}].contours[{contour_index}].samples_2d "
                    "must contain at least two XY points"
                )
            if not np.all(np.isfinite(points)):
                raise ValueError(
                    f"sections[{section_index}].contours[{contour_index}].samples_2d "
                    "must contain only finite coordinates"
                )
            validated_contours.append(
                (
                    points,
                    bool(contour.get("closed", False)),
                    str(contour.get("role", "other")),
                    int(contour.get("nesting_depth", 0) or 0),
                )
            )
        panel_contours.append(validated_contours)

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise ImportError("Section atlas rendering requires matplotlib") from error

    rows = (len(selected_sections) + columns - 1) // columns
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(image_size_per_panel[0] * columns, image_size_per_panel[1] * rows),
        constrained_layout=True,
        squeeze=False,
    )
    axes_array = axes.ravel()
    try:
        for section_index, (axes_item, section, contours) in enumerate(
            zip(axes_array, selected_sections, panel_contours)
        ):
            for points, closed, role, nesting_depth in contours:
                if not closed:
                    color, linestyle, fill = "#9467bd", "--", False
                elif role == "hole":
                    color, linestyle, fill = "#d62728", "-", False
                elif role == "material" and nesting_depth > 0:
                    color, linestyle, fill = "#2ca02c", "-.", True
                elif role == "material":
                    color, linestyle, fill = "#1f77b4", "-", True
                else:
                    color, linestyle, fill = "#7f7f7f", ":", False
                axes_item.plot(
                    points[:, 0],
                    points[:, 1],
                    color=color,
                    linestyle=linestyle,
                    linewidth=1.8,
                )
                if fill:
                    axes_item.fill(
                        points[:, 0],
                        points[:, 1],
                        color=color,
                        alpha=0.14,
                    )

            if not contours:
                plane = section.get("plane", {})
                axes_item.text(
                    0.5,
                    0.5,
                    "No section contours\n"
                    f"origin={plane.get('origin', 'unknown')}\n"
                    f"normal={plane.get('normal', 'unknown')}",
                    ha="center",
                    va="center",
                    transform=axes_item.transAxes,
                )
                axes_item.set_xlim(-1.0, 1.0)
                axes_item.set_ylim(-1.0, 1.0)

            title = (
                selected_titles[section_index]
                if selected_titles is not None
                else str(section.get("section_id", f"Section {section_index + 1}"))
            )
            closed_count = int(section.get("closed_contour_count", 0))
            open_count = int(section.get("open_contour_count", 0))
            material_area = float(section.get("material_area", 0.0))
            axes_item.set_title(
                f"{title}\nMaterial area {material_area:.6g} mm^2 | "
                f"closed {closed_count} | open {open_count}"
            )
            axes_item.set_xlabel("Local X (mm)")
            axes_item.set_ylabel("Local Y (mm)")
            axes_item.set_aspect("equal", adjustable="datalim")
            axes_item.grid(True, color="#d9d9d9", linewidth=0.6, linestyle=":")

        for axes_item in axes_array[len(selected_sections) :]:
            axes_item.set_visible(False)

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output, dpi=dpi)
    finally:
        plt.close(figure)
    return output
