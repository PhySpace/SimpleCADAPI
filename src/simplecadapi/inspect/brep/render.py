"""Fast, smooth multi-view rendering for BREP inspection."""

from __future__ import annotations

import colorsys
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, Union

import numpy as np

from simplecadapi._cpp.occt.BRep import BRep_Builder, BRep_Tool
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve
from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_Copy
from simplecadapi._cpp.occt.BRepMesh import BRepMesh_IncrementalMesh
from simplecadapi._cpp.occt.GCPnts import GCPnts_QuasiUniformDeflection
from simplecadapi._cpp.occt.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_REVERSED,
    TopAbs_SOLID,
)
from simplecadapi._cpp.occt.TopExp import TopExp, TopExp_Explorer
from simplecadapi._cpp.occt.TopTools import TopTools_IndexedMapOfShape
from simplecadapi._cpp.occt.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Edge, TopoDS_Shape
from simplecadapi._cpp.occt.IFSelect import IFSelect_RetDone
from simplecadapi._cpp.occt.Quantity import Quantity_ColorRGBA
from simplecadapi._cpp.occt.STEPCAFControl import STEPCAFControl_Reader
from simplecadapi._cpp.occt.TCollection import TCollection_ExtendedString
from simplecadapi._cpp.occt.TDocStd import TDocStd_Document
from simplecadapi._cpp.occt.TopLoc import TopLoc_Location
from simplecadapi._cpp.occt.XCAFApp import XCAFApp_Application
from simplecadapi._cpp.occt.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from simplecadapi._cpp.occt.XCAFPrs import (
    XCAFPrs,
    XCAFPrs_DocumentExplorer,
    XCAFPrs_DocumentExplorerFlags_OnlyLeafNodes,
    XCAFPrs_IndexedDataMapOfShapeStyle,
)
from simplecadapi._cpp.occt.TDF import TDF_LabelSequence
from simplecadapi._cpp.occt.TDataStd import TDataStd_Name

from ._raster import LineData, MeshData, PointData, render_comparison, render_views as _render_views
from .io import load_step_rshape
from .model import BRepModel, index_shape_rbrepmodel, load_step_rbrepmodel

DEFAULT_VIEWS: tuple[tuple[float, float, str], ...] = (
    (28.0, -45.0, "isometric"),
    (90.0, -90.0, "top / X-Y"),
    (0.0, -90.0, "front / X-Z"),
    (0.0, 0.0, "side / Y-Z"),
)













def _validate_render_output_path(output_path: str | Path) -> Path:
    output = Path(output_path)
    if output.suffix.lower() not in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        raise ValueError("render output must be PNG, JPEG, or TIFF")
    return output


# VTK offscreen rendering on macOS intermittently crashes natively
# (SIGTRAP/SIGSEGV/SIGBUS) under heavy system load; extra attempts with real
# backoff absorb those crash bursts.








def _compound(shapes: Sequence[TopoDS_Shape]) -> TopoDS_Shape:
    if len(shapes) == 1:
        return shapes[0]
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, shape)
    return compound

def _rgba_tuple(color: Quantity_ColorRGBA) -> tuple[float, float, float, float]:
    rgb = color.GetRGB()
    return (float(rgb.Red()), float(rgb.Green()), float(rgb.Blue()), float(color.Alpha()))

def _label_name(label) -> str:
    if label.IsNull():
        return ""
    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return attribute.Get().ToExtString()
    return ""


def _node_name(node) -> str:
    return _label_name(node.Label) or _label_name(node.RefLabel) or "<unnamed>"

def _path_segment(node) -> str:
    return f"{_node_name(node)}[{node.Id.ToCString()}]"


def _component_records(document: TDocStd_Document) -> list[dict[str, object]]:
    explorer = XCAFPrs_DocumentExplorer(document, 0)
    records: list[dict[str, object]] = []
    while explorer.More():
        node = explorer.Current()
        name = _node_name(node)
        records.append(
            {
                "name": name,
                "path": tuple(
                    _path_segment(explorer.Current(depth))
                    for depth in range(explorer.CurrentDepth() + 1)
                ),
                "node_id": node.Id.ToCString(),
                "depth": int(explorer.CurrentDepth()),
                "assembly": bool(node.IsAssembly),
                "shape": XCAFDoc_ShapeTool.GetShape_s(node.RefLabel).Moved(
                    node.Location,
                    False,
                ),
            }
        )
        explorer.Next()
    return records


def _load_step_xcaf_document(
    path: str | Path,
) -> tuple[TDocStd_Document, TopoDS_Shape, dict[int, tuple[float, float, float, float]]]:
    """Load one styled STEP/XCAF document and its effective face colors."""
    application = XCAFApp_Application.GetApplication_s()
    del application
    document = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    status = reader.ReadFile(str(path))
    if status != IFSelect_RetDone or not reader.Transfer(document):
        raise ValueError(f"Could not read styled STEP file {path}: {status}")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    if roots.Length() < 1:
        raise ValueError(f"STEP file {path} contains no free shapes")
    root = shape_tool.GetOneShape()
    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(root, TopAbs_FACE, face_map)
    face_colors: dict[int, tuple[float, float, float, float]] = {}

    explorer = XCAFPrs_DocumentExplorer(
        document,
        XCAFPrs_DocumentExplorerFlags_OnlyLeafNodes,
    )
    while explorer.More():
        node = explorer.Current()
        style = node.Style
        if style.IsVisible() and style.IsSetColorSurf():
            shape = XCAFDoc_ShapeTool.GetShape_s(node.RefLabel).Moved(
                node.Location,
                False,
            )
            faces = TopTools_IndexedMapOfShape()
            TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
            color = _rgba_tuple(style.GetColorSurfRGBA())
            for index in range(1, faces.Extent() + 1):
                root_index = face_map.FindIndex(faces.FindKey(index))
                if root_index > 0:
                    face_colors[root_index] = color
        explorer.Next()

    settings = XCAFPrs_IndexedDataMapOfShapeStyle()
    for index in range(1, roots.Length() + 1):
        XCAFPrs.CollectStyleSettings_s(
            roots.Value(index),
            TopLoc_Location(),
            settings,
        )
    for index in range(1, settings.Extent() + 1):
        shape = settings.FindKey(index)
        style = settings.FindFromIndex(index)
        if (
            shape.ShapeType() == TopAbs_FACE
            and style.IsVisible()
            and style.IsSetColorSurf()
        ):
            root_index = face_map.FindIndex(shape)
            if root_index > 0:
                face_colors[root_index] = _rgba_tuple(style.GetColorSurfRGBA())
    return document, root, face_colors
def _load_step_xcaf(
    path: str | Path,
) -> tuple[TopoDS_Shape, dict[int, tuple[float, float, float, float]]]:
    """Load STEP geometry and effective per-face XCAF presentation colors."""
    _, root, face_colors = _load_step_xcaf_document(path)
    return root, face_colors


def _mesh_geometry(
    shapes: Sequence[TopoDS_Shape],
    linear_deflection: float,
    angular_deflection: float,
    face_colors: Mapping[int, tuple[float, float, float, float]] | None = None,
):
    """Tessellate BREP faces into one triangle mesh (:class:`MeshData`).

    OpenCascade supplies per-face vertex normals. Face-local vertices remain
    separate, which keeps sharp BREP boundaries sharp while smoothing adjacent
    triangles on the same analytic face.
    """
    if not shapes:
        return None
    if linear_deflection <= 0.0 or angular_deflection <= 0.0:
        raise ValueError("mesh deflections must be greater than zero")

    copy = BRepBuilderAPI_Copy(_compound(shapes), True, False)
    render_shape = copy.Shape()
    BRepMesh_IncrementalMesh(
        render_shape,
        linear_deflection,
        False,
        angular_deflection,
        True,
    )

    point_blocks: list[np.ndarray] = []
    normal_blocks: list[np.ndarray] = []
    triangle_blocks: list[np.ndarray] = []
    point_offset = 0
    color_blocks: list[np.ndarray] = []
    source_face_index = 0
    explorer = TopExp_Explorer(render_shape, TopAbs_FACE)
    while explorer.More():
        source_face_index += 1
        face = TopoDS.Face_s(explorer.Current())
        location = face.Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is None or triangulation.NbTriangles() == 0:
            explorer.Next()
            continue
        if not triangulation.HasNormals():
            triangulation.ComputeNormals()

        transform = location.Transformation()
        reversed_face = face.Orientation() == TopAbs_REVERSED
        points = np.empty((triangulation.NbNodes(), 3), dtype=np.float32)
        normals = np.empty_like(points)
        for node_index in range(1, triangulation.NbNodes() + 1):
            point = triangulation.Node(node_index)
            point.Transform(transform)
            points[node_index - 1] = point.Coord()
            normal = triangulation.Normal(node_index)
            normal.Transform(transform)
            normals[node_index - 1] = normal.Coord()
        if reversed_face:
            normals *= -1.0

        triangles = np.empty(
            (triangulation.NbTriangles(), 3),
            dtype=np.int64,
        )
        for triangle_index in range(1, triangulation.NbTriangles() + 1):
            triangle = triangulation.Triangle(triangle_index)
            indices = [
                triangle.Value(1) - 1,
                triangle.Value(2) - 1,
                triangle.Value(3) - 1,
            ]
            if reversed_face:
                indices[1], indices[2] = indices[2], indices[1]
            triangles[triangle_index - 1] = np.asarray(indices) + point_offset
        if face_colors is not None:
            rgba = face_colors.get(source_face_index, (0.55, 0.64, 0.73, 1.0))
            color = np.asarray(
                [round(255.0 * component) for component in rgba],
                dtype=np.uint8,
            )
            color_blocks.append(
                np.repeat(color[None, :], len(triangles), axis=0)
            )

        point_blocks.append(points)
        normal_blocks.append(normals)
        triangle_blocks.append(triangles)
        point_offset += len(points)
        explorer.Next()

    if not point_blocks:
        raise ValueError("OpenCascade produced no renderable triangles")

    points = np.concatenate(point_blocks)
    normals = np.concatenate(normal_blocks)
    triangles = np.concatenate(triangle_blocks)
    colors = np.concatenate(color_blocks) if color_blocks else None
    return MeshData(
        points=points.astype(np.float32, copy=False),
        normals=normals.astype(np.float32, copy=False),
        triangles=triangles.astype(np.uint32, copy=False),
        colors=colors,
    )



_EDGE_DEFLECTION_CAP = 0.04  # mm chord error cap for BRep edge discretization


def _sample_edge(
    edge: TopoDS_Edge,
    *,
    deflection: float | None = None,
    sample_count: int | None = None,
) -> np.ndarray:
    if BRep_Tool.Degenerated_s(edge):
        return np.empty((0, 3), dtype=np.float32)
    adaptor = BRepAdaptor_Curve(edge)
    first = float(adaptor.FirstParameter())
    last = float(adaptor.LastParameter())
    parameters: list[float]
    if sample_count is not None:
        parameters = np.linspace(first, last, sample_count).tolist()
    else:
        assert deflection is not None  # narrowed by the caller-side validation
        sampler = GCPnts_QuasiUniformDeflection(adaptor, float(deflection))
        if sampler.IsDone() and sampler.NbPoints() >= 2:
            return np.asarray(
                [sampler.Value(index).Coord() for index in range(1, sampler.NbPoints() + 1)],
                dtype=np.float32,
            )
        parameters = [first, last]
    return np.asarray(
        [adaptor.Value(float(parameter)).Coord() for parameter in parameters],
        dtype=np.float32,
    )


def _edge_geometry(
    shapes: Sequence[TopoDS_Shape],
    *,
    deflection: float | None = None,
    sample_count: int | None = None,
):
    if not shapes:
        return None
    if deflection is not None and deflection <= 0.0:
        raise ValueError("edge deflection must be greater than zero")
    if sample_count is not None and sample_count < 2:
        raise ValueError("edge sample count must be at least two")

    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(_compound(shapes), TopAbs_EDGE, edge_map)
    point_blocks: list[np.ndarray] = []
    cell_blocks: list[np.ndarray] = []
    point_offset = 0
    for index in range(1, edge_map.Extent() + 1):
        points = _sample_edge(
            TopoDS.Edge_s(edge_map.FindKey(index)),
            deflection=deflection,
            sample_count=sample_count,
        )
        if len(points) < 2:
            continue
        point_blocks.append(points)
        cell_blocks.append(np.arange(point_offset, point_offset + len(points), dtype=np.int64))
        point_offset += len(points)
    if not point_blocks:
        return None

    points = np.concatenate(point_blocks)
    offsets = np.empty(len(cell_blocks) + 1, dtype=np.int64)
    offsets[0] = 0
    offsets[1:] = np.cumsum([len(cell) for cell in cell_blocks])
    return LineData(points=points.astype(np.float32, copy=False), starts=offsets.astype(np.uint32))



def _hex_rgb(value: str) -> tuple[float, float, float]:
    token = value.removeprefix("#")
    return tuple(int(token[index : index + 2], 16) / 255.0 for index in (0, 2, 4))










def _point_geometry(points: Sequence[Sequence[float]]):
    if not len(points):
        return None
    return PointData(points=np.asarray(points, dtype=np.float32))





























def render_shape_views_rpath(
    shape: TopoDS_Shape,
    output_path: str | Path,
    *,
    title: str = "BREP views",
    views: Sequence[tuple[float, float, str]] = DEFAULT_VIEWS,
    image_size: tuple[float, float] = (18.0, 12.0),
    dpi: int = 180,
    linear_deflection: float = 0.12,
    angular_deflection: float = 0.18,
    show_brep_edges: bool = True,
) -> Path:
    """Render smooth shaded BREP views with true topology edges by default.

    ``show_brep_edges`` draws exact topological edges sampled from the BREP; it
    never exposes the internal triangle edges used by the GPU.
    """
    base = _mesh_geometry([shape], linear_deflection, angular_deflection)
    edges = (
        _edge_geometry([shape], deflection=min(linear_deflection, _EDGE_DEFLECTION_CAP))
        if show_brep_edges
        else None
    )
    return _render_views(
        base,
        output_path,
        title=title,
        views=views,
        image_size=image_size,
        dpi=dpi,
        brep_edges=edges,
        supersample=2,
        style="standard",
    )


def inspect_step_components_rdescriptorlist(step_path: str | Path) -> list[dict[str, object]]:
    """List targetable XCAF component occurrences with unique hierarchy paths."""
    document, _, _ = _load_step_xcaf_document(step_path)
    result: list[dict[str, object]] = []
    for record in _component_records(document):
        shape = record["shape"]
        solid_map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_SOLID, solid_map)
        result.append(
            {
                "name": record["name"],
                "path": "/".join(record["path"]),
                "node_id": record["node_id"],
                "depth": record["depth"],
                "assembly": record["assembly"],
                "solid_count": solid_map.Extent(),
            }
        )
    return result


def _resolve_step_components(
    document: TDocStd_Document,
    selectors: Sequence[str],
) -> list[dict[str, object]]:
    if not selectors:
        raise ValueError("At least one component name or path is required")
    records = _component_records(document)
    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    for selector in selectors:
        token = str(selector).strip()
        if not token:
            raise ValueError("Component selectors must not be empty")
        path_matches = [
            record
            for record in records
            if "/".join(record["path"]) == token or record["node_id"] == token
        ]
        matches = path_matches or [
            record for record in records if record["name"] == token
        ]
        if not matches:
            candidates = sorted(
                {
                    record["name"]
                    for record in records
                    if token.casefold() in str(record["name"]).casefold()
                }
            )[:12]
            suffix = f"; nearby names: {', '.join(candidates)}" if candidates else ""
            raise ValueError(f"No STEP component matches {token!r}{suffix}")
        for record in matches:
            node_id = str(record["node_id"])
            if node_id not in selected_ids:
                selected.append(record)
                selected_ids.add(node_id)
    return selected


def render_step_components_rpath(
    step_path: str | Path,
    component_names: Sequence[str],
    output_path: str | Path,
    *,
    with_context: bool = True,
    title: str | None = None,
    views: Sequence[tuple[float, float, str]] = DEFAULT_VIEWS,
    image_size: tuple[float, float] = (18.0, 12.0),
    dpi: int = 180,
    linear_deflection: float = 0.12,
    angular_deflection: float = 0.18,
) -> Path:
    """Render named XCAF component occurrences, optionally in assembly context."""
    source = Path(step_path)
    document, root, _ = _load_step_xcaf_document(source)
    selected = _resolve_step_components(document, component_names)
    shapes = [record["shape"] for record in selected]
    selected_title = ", ".join(str(record["name"]) for record in selected)
    selected_mesh = _mesh_geometry(shapes, linear_deflection, angular_deflection)
    selected_edges = _edge_geometry(shapes, deflection=linear_deflection)
    if with_context:
        return _render_views(
            _mesh_geometry([root], linear_deflection, angular_deflection),
            output_path,
            title=title or f"{source.name} - {selected_title}",
            views=views,
            image_size=image_size,
            dpi=dpi,
            context_opacity=0.12,
            highlighted=selected_mesh,
            highlighted_edges=selected_edges,
        )
    return _render_views(
        selected_mesh,
        output_path,
        title=title or f"{source.name} - {selected_title}",
        views=views,
        image_size=image_size,
        dpi=dpi,
        brep_edges=selected_edges,
    )


_NAMED_COLORS: Mapping[str, tuple[float, float, float]] = {
    "red": (0.90, 0.18, 0.20),
    "crimson": (0.86, 0.08, 0.24),
    "orange": (0.95, 0.55, 0.15),
    "gold": (0.85, 0.65, 0.13),
    "yellow": (0.95, 0.85, 0.15),
    "lime": (0.50, 0.80, 0.20),
    "green": (0.20, 0.75, 0.35),
    "teal": (0.15, 0.70, 0.70),


    "cyan": (0.15, 0.85, 0.90),
    "skyblue": (0.40, 0.75, 0.95),
    "blue": (0.20, 0.35, 0.95),
    "navy": (0.15, 0.15, 0.55),
    "purple": (0.55, 0.25, 0.80),
    "violet": (0.60, 0.45, 0.90),
    "magenta": (0.90, 0.15, 0.70),
    "pink": (0.95, 0.30, 0.70),
    "salmon": (0.95, 0.55, 0.45),
    "brown": (0.60, 0.40, 0.20),
    "tan": (0.80, 0.65, 0.45),
    "olive": (0.55, 0.55, 0.20),
    "gray": (0.55, 0.55, 0.55),
    "silver": (0.75, 0.75, 0.78),
    "black": (0.10, 0.10, 0.12),
    "white": (0.96, 0.96, 0.96),
}
def _distinct_entity_colors(count: int) -> list[tuple[float, float, float]]:
    """Return deterministic high-contrast colors with no duplicate RGB values."""
    if count < 0:
        raise ValueError("color count must not be negative")
    colors: list[tuple[float, float, float]] = []
    golden_ratio = 0.6180339887498949
    for index in range(count):
        hue = (0.97 + index * golden_ratio) % 1.0
        saturation = 0.72 if index % 2 == 0 else 0.86
        value = 0.92 if index % 3 else 0.78
        colors.append(tuple(float(channel) for channel in colorsys.hsv_to_rgb(hue, saturation, value)))
    return colors


def _entity_anchor(descriptor: Mapping[str, Any]) -> tuple[float, float, float]:
    geometry = descriptor["geometry"]
    values = geometry.get("centroid") or geometry.get("coordinates")
    if values is None:
        values = descriptor["bounding_box"]["center"]
    return tuple(float(value) for value in values)

def _entity_map_legend(
    entries: Sequence[tuple[str, str, tuple[float, float, float]]],
    *,
    columns: int = 3,
) -> list[tuple[str, tuple[float, float, float]]]:
    """Return compact ID/type rows; columns are populated top-to-bottom."""
    if columns < 1:
        raise ValueError("legend_columns must be at least one")
    return [(f"{entity_id} · {geometry_type}", color) for entity_id, geometry_type, color in entries]


def render_entity_map_rpath(
    model_or_path: BRepModel | TopoDS_Shape | str | Path,
    entity_ids: Sequence[str],
    output_path: str | Path,
    *,
    title: str = "BREP entity map",
    views: Sequence[tuple[float, float, str]] = DEFAULT_VIEWS,
    highlight_edge_width: float = 6.0,
    highlight_point_size: float = 18.0,
    image_size: tuple[float, float] = (18.0, 12.0),
    dpi: int = 180,
    linear_deflection: float = 0.12,
    angular_deflection: float = 0.18,
    edge_samples: int = 96,
    context_opacity: float = 1.0,
    label_mode: Literal["auto", "callout", "legend", "none"] = "legend",
    max_callouts: int = 4,
    legend_columns: int = 3,
) -> Path:
    """Render stable BREP entity IDs without flattening model depth.

    The base model stays opaque by default and keeps its true BREP edges.
    Bodies use colored topology edges, faces use a restrained translucent tint
    plus boundary edges, edges use thick curves, and vertices use colored
    points. ``highlight_edge_width`` and ``highlight_point_size`` make selected
    edges and vertices visually dominant. A dedicated ID/type key is the safe
    default; callouts remain available for focused selections.
    """
    if edge_samples < 2:
        raise ValueError("edge_samples must be at least two")
    if not 0.0 <= context_opacity <= 1.0:
        raise ValueError("context_opacity must be between zero and one")
    if label_mode not in {"auto", "callout", "legend", "none"}:
        raise ValueError("label_mode must be auto, callout, legend, or none")
    if max_callouts < 1:
        raise ValueError("max_callouts must be at least one")
    if label_mode == "callout" and len(entity_ids) > max_callouts:
        raise ValueError(
            f"callout mode supports at most {max_callouts} entities; use legend mode"
        )
    if legend_columns < 1:
        raise ValueError("legend_columns must be at least one")
    if not entity_ids:
        raise ValueError("At least one entity ID is required")
    model = (
        model_or_path
        if isinstance(model_or_path, BRepModel)
        else index_shape_rbrepmodel(model_or_path)
        if isinstance(model_or_path, TopoDS_Shape)
        else load_step_rbrepmodel(model_or_path)
    )
    canonical_ids: list[str] = []
    resolved: list[tuple[str, TopoDS_Shape, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for entity_id in entity_ids:
        kind, index, shape = model.resolve_entity(entity_id)
        canonical = f"{kind}:{index}"
        if canonical in seen:
            raise ValueError(f"duplicate entity ID {canonical!r}")
        seen.add(canonical)
        canonical_ids.append(canonical)
        resolved.append((kind, shape, model.describe_entity(canonical)))

    surface_groups: list[tuple[Any, tuple[float, float, float], float]] = []
    edge_groups: list[tuple[Any, tuple[float, float, float]]] = []
    point_groups: list[tuple[Any, tuple[float, float, float]]] = []
    label_entries: list[
        tuple[str, str, tuple[float, float, float]]
    ] = []
    callouts: list[tuple] = []
    datasets: dict[str, Any] = {}  # canonical id -> its own geometry, where an occluded callout re-anchors
    for canonical, color, (kind, shape, descriptor) in zip(
        canonical_ids,
        _distinct_entity_colors(len(resolved)),
        resolved,
        strict=True,
    ):
        anchor = _entity_anchor(descriptor)
        if kind == "face":
            face_mesh = _mesh_geometry([shape], linear_deflection, angular_deflection)
            surface_groups.append((face_mesh, color, min(0.28, context_opacity)))
            edge_groups.append((_edge_geometry([shape], deflection=linear_deflection), color))
            datasets[canonical] = face_mesh
        elif kind == "body":
            body_edges = _edge_geometry([shape], deflection=linear_deflection)
            edge_groups.append((body_edges, color))
            datasets[canonical] = body_edges
        elif kind == "edge":
            line_geometry = _edge_geometry([shape], sample_count=edge_samples)
            edge_groups.append((line_geometry, color))
            datasets[canonical] = line_geometry
        anchor_points = _point_geometry([anchor])
        point_groups.append((anchor_points, color))
        datasets.setdefault(canonical, anchor_points)
        geometry_type = str(descriptor["geometry"]["type"])
        label_entries.append((canonical, geometry_type, color))
        callouts.append((f"{canonical} · {geometry_type}", anchor, color, canonical))

    effective_label_mode = (
        "callout" if label_mode == "auto" and len(resolved) <= max_callouts
        else "legend" if label_mode == "auto"
        else label_mode
    )
    legend = (
        _entity_map_legend(label_entries, columns=legend_columns)
        if effective_label_mode == "legend"
        else None
    )

    return _render_views(
        _mesh_geometry([model.root], linear_deflection, angular_deflection),
        output_path,
        legend_panel=effective_label_mode == "legend",
        title=title,
        views=views,
        image_size=image_size,
        dpi=dpi,
        context_opacity=context_opacity,
        brep_edges=_edge_geometry([model.root], deflection=linear_deflection),
        highlighted_groups=surface_groups,
        highlighted_edge_groups=edge_groups,
        highlighted_point_groups=point_groups,
        highlight_edge_width=highlight_edge_width,
        highlight_point_size=highlight_point_size,
        legend=legend,
        legend_columns=legend_columns,
        callouts=callouts if effective_label_mode == "callout" else None,
        datasets=datasets,
    )
def render_entity_kind_maps_rpath(
    model_or_path: BRepModel | TopoDS_Shape | str | Path,
    entity_ids: Sequence[str],
    output_dir: str | Path,
    *,
    title: str = "BREP entity map",
    views: Sequence[tuple[float, float, str]] = DEFAULT_VIEWS,
    image_size: tuple[float, float] = (18.0, 12.0),
    dpi: int = 180,
    linear_deflection: float = 0.12,
    angular_deflection: float = 0.18,
    edge_samples: int = 96,
    context_opacity: float = 1.0,
    highlight_edge_width: float = 6.0,
    highlight_point_size: float = 18.0,
    label_mode: Literal["auto", "callout", "legend", "none"] = "legend",
    max_callouts: int = 4,
    legend_columns: int = 3,
) -> dict[str, Path]:
    """Render independent face, edge, and vertex highlight maps."""
    if not entity_ids:
        raise ValueError("At least one entity ID is required")
    if isinstance(model_or_path, BRepModel):
        model = model_or_path
    elif isinstance(model_or_path, TopoDS_Shape):
        model = index_shape_rbrepmodel(model_or_path)
    else:
        model = load_step_rbrepmodel(model_or_path)
    grouped: dict[str, list[str]] = {"face": [], "edge": [], "vertex": []}
    for entity_id in entity_ids:
        kind, index, _ = model.resolve_entity(entity_id)
        if kind in grouped:
            grouped[kind].append(f"{kind}:{index}")
    output_root = Path(output_dir)
    result: dict[str, Path] = {}
    for kind, ids in grouped.items():
        if not ids:
            continue
        result[kind] = render_entity_map_rpath(
            model,
            ids,
            output_root / f"{kind}-map.png",
            title=f"{title} · {kind}s",
            views=views,
            image_size=image_size,
            dpi=dpi,
            linear_deflection=linear_deflection,
            angular_deflection=angular_deflection,
            edge_samples=edge_samples,
            context_opacity=context_opacity,
            highlight_edge_width=highlight_edge_width,
            highlight_point_size=highlight_point_size,
            label_mode=label_mode,
            max_callouts=max_callouts,
            legend_columns=legend_columns,
        )
    return result


ColorSpec = Union[int, str, tuple[float, float, float]]
"""Color spec: palette index, #RRGGBB/#RGB or named string, or (r, g, b) tuple."""


def _resolve_color(
    spec: ColorSpec,
    palette: Sequence[ColorSpec] | None = None,
) -> tuple[float, float, float]:
    """Resolve a color spec to an (r, g, b) tuple in 0..1."""
    if isinstance(spec, int):
        if palette is None:
            raise ValueError("an integer color requires a palette")
        if spec < 0 or spec >= len(palette):
            raise ValueError(f"palette index {spec} out of range 0..{len(palette) - 1}")
        return _resolve_color(palette[spec])
    if isinstance(spec, str):
        value = spec.strip()
        if value.startswith("#"):
            digits = value[1:]
            if len(digits) == 6:
                return tuple(int(digits[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
            if len(digits) == 3:
                return tuple(int(digits[i] * 2, 16) / 255.0 for i in (0, 1, 2))
            raise ValueError(f"hex color must be #RRGGBB or #RGB, got {spec!r}")
        name = value.casefold()
        if name in _NAMED_COLORS:
            return _NAMED_COLORS[name]
        raise ValueError(
            f"unknown color {spec!r}; use #RRGGBB, a named color "
            f"({', '.join(sorted(_NAMED_COLORS))}), or an (r, g, b) tuple"
        )
    if isinstance(spec, tuple) and len(spec) == 3:
        return tuple(float(channel) for channel in spec)
    raise ValueError(f"invalid color spec {spec!r}")


def render_step_components_colored_rpath(
    step_path: str | Path,
    component_colors: Mapping[str, ColorSpec],
    output_path: str | Path,
    *,
    palette: Sequence[ColorSpec] | None = None,
    with_context: bool = True,
    title: str | None = None,
    views: Sequence[tuple[float, float, str]] = DEFAULT_VIEWS,
    image_size: tuple[float, float] = (18.0, 12.0),
    dpi: int = 180,
    linear_deflection: float = 0.12,
    angular_deflection: float = 0.18,
    show_legend: bool = True,
) -> Path:
    """Render multiple STEP components, each in its own color.

    The recommended, most semantic form maps each component selector
    directly to a color NAME::

        render_step_components_colored_rpath(
            "assembly.step",
            {"SPK-2030X4MM": "cyan", "USER_LIBRARY-USB_TYPE_C_PORT__S": "purple"},
            "out.png",
        )

    Selectors resolve like ``render_step_components_rpath`` (names, paths,
    or node ids) and multiple occurrences of one name share its color.
    ``component_colors`` values accept a named color from the built-in set
    (red, crimson, orange, gold, yellow, lime, green, teal, cyan, skyblue,
    blue, navy, purple, violet, magenta, pink, salmon, brown, tan, olive,
    gray, silver, black, white), a ``#RRGGBB`` / ``#RGB`` hex string, an
    ``(r, g, b)`` 0..1 tuple, or an integer palette index (with ``palette``).
    The result shows every selected solid at once, color-coded, with an
    optional color legend so the geometry can be matched to per-component
    text.
    """
    if not component_colors:
        raise ValueError("At least one component color mapping is required")
    source = Path(step_path)
    document, root, _ = _load_step_xcaf_document(source)
    selectors = list(component_colors)
    selected = _resolve_step_components(document, selectors)
    selector_to_records: dict[str, list[dict[str, object]]] = {}
    used: set[str] = set()
    for selector in selectors:
        token = str(selector).strip()
        matches = [
            record
            for record in selected
            if record["node_id"] == token
            or "/".join(record["path"]) == token
            or str(record["name"]) == token
        ]
        if not matches:
            raise ValueError(f"selector {token!r} resolved to no component")
        selector_to_records[token] = matches
        used.update(record["node_id"] for record in matches)
    if len(used) != len(selected):
        unresolved = [
            str(record["name"])
            for record in selected
            if record["node_id"] not in used
        ]
        raise ValueError(f"component colors did not cover selected components: {unresolved}")

    groups: list[tuple[Any, tuple[float, float, float], float]] = []
    edge_groups: list[tuple[Any, tuple[float, float, float]]] = []
    legend: list[tuple[str, tuple[float, float, float]]] = []
    legend_seen: set[tuple[str, tuple[float, float, float]]] = set()
    for selector in selectors:
        spec = component_colors[selector]
        rgb = _resolve_color(spec, palette)
        for record in selector_to_records[str(selector).strip()]:
            shape = record["shape"]
            groups.append(
                (_mesh_geometry([shape], linear_deflection, angular_deflection), rgb, 1.0)
            )
            edge_groups.append((_edge_geometry([shape], deflection=linear_deflection), rgb))
        entry = (f"{str(selector).strip()} ({spec})", rgb)
        if show_legend and entry not in legend_seen:
            legend.append(entry)
            legend_seen.add(entry)

    if with_context:
        return _render_views(
            _mesh_geometry([root], linear_deflection, angular_deflection),
            output_path,
            title=title or f"{source.name} - colored components",
            views=views,
            image_size=image_size,
            dpi=dpi,
            context_opacity=0.12,
            highlighted_groups=groups,
            highlighted_edge_groups=edge_groups,
            legend=legend,
        )
    return _render_views(
        None,
        output_path,
        title=title or f"{source.name} - colored components",
        views=views,
        image_size=image_size,
        dpi=dpi,
        highlighted_groups=groups,
        highlighted_edge_groups=edge_groups,
        legend=legend,
    )


def render_step_views_rpath(
    step_path: str | Path,
    output_path: str | Path,
    **kwargs,
) -> Path:
    """Load STEP/XCAF colors and render smooth faces with true BREP edges."""
    source = Path(step_path)
    kwargs.setdefault("title", f"{source.name} - BREP views")
    shape, face_colors = _load_step_xcaf(source)
    views = kwargs.pop("views", DEFAULT_VIEWS)
    image_size = kwargs.pop("image_size", (18.0, 12.0))
    dpi = kwargs.pop("dpi", 180)
    linear_deflection = kwargs.pop("linear_deflection", 0.12)
    angular_deflection = kwargs.pop("angular_deflection", 0.18)
    show_brep_edges = kwargs.pop("show_brep_edges", True)
    title = kwargs.pop("title")
    if kwargs:
        unknown = ", ".join(sorted(kwargs))
        raise TypeError(f"Unexpected render options: {unknown}")
    return _render_views(
        _mesh_geometry(
            [shape],
            linear_deflection,
            angular_deflection,
            face_colors=face_colors,
        ),
        output_path,
        title=title,
        views=views,
        image_size=image_size,
        dpi=dpi,
        brep_edges=(
            _edge_geometry([shape], deflection=linear_deflection)
            if show_brep_edges
            else None
        ),
    )


def render_step_comparison_rpath(
    target_step_path: str | Path,
    current_step_path: str | Path,
    output_path: str | Path,
    *,
    views: Sequence[tuple[float, float, str]] = DEFAULT_VIEWS,
    image_size: tuple[float, float] = (16.0, 20.0),
    dpi: int = 160,
    linear_deflection: float = 0.12,
    angular_deflection: float = 0.18,
    show_brep_edges: bool = True,
) -> Path:
    """Render target and current STEP models with identical cameras and scale.

    Shared views, union bounds, tessellation, and BREP-edge settings keep
    independent camera fitting from hiding size or placement differences. The
    image is diagnostic evidence and does not replace strict comparison.
    """
    if not views:
        raise ValueError("at least one render view is required")
    if dpi < 1 or image_size[0] <= 0.0 or image_size[1] <= 0.0:
        raise ValueError("image size and DPI must be greater than zero")
    target_path = Path(target_step_path)
    current_path = Path(current_step_path)
    target_shape = load_step_rshape(target_path)
    current_shape = load_step_rshape(current_path)
    target_polydata = _mesh_geometry(
        [target_shape], linear_deflection, angular_deflection
    )
    current_polydata = _mesh_geometry(
        [current_shape], linear_deflection, angular_deflection
    )
    target_edges = (
        _edge_geometry([target_shape], deflection=linear_deflection)
        if show_brep_edges
        else None
    )
    current_edges = (
        _edge_geometry([current_shape], deflection=linear_deflection)
        if show_brep_edges
        else None
    )

    target_box = load_step_rbrepmodel(target_path).summary()["bounding_box"]
    current_box = load_step_rbrepmodel(current_path).summary()["bounding_box"]
    minimum = np.minimum(target_box["min"], current_box["min"])
    maximum = np.maximum(target_box["max"], current_box["max"])
    shared_bounds = (
        float(minimum[0]),
        float(maximum[0]),
        float(minimum[1]),
        float(maximum[1]),
        float(minimum[2]),
        float(maximum[2]),
    )

    return render_comparison(
        (
            ("Original", target_path.name, target_polydata, target_edges),
            ("Reconstructed", current_path.name, current_polydata, current_edges),
        ),
        output_path,
        views=views,
        image_size=image_size,
        dpi=dpi,
        shared_bounds=shared_bounds,
    )


def render_region_rpath(
    model_or_path: BRepModel | TopoDS_Shape | str | Path,
    entity_ids: Sequence[str],
    output_path: str | Path,
    *,
    neighborhood_depth: int = 0,
    title: str = "Highlighted BREP region",
    views: Sequence[tuple[float, float, str]] = DEFAULT_VIEWS,
    image_size: tuple[float, float] = (18.0, 12.0),
    dpi: int = 180,
    linear_deflection: float = 0.12,
    angular_deflection: float = 0.18,
    edge_samples: int = 96,
    highlight_edge_width: float = 6.0,
    highlight_point_size: float = 18.0,
) -> Path:
    """Highlight stable entities and their optional topology neighborhood."""
    if edge_samples < 2:
        raise ValueError("edge_samples must be at least two")
    if isinstance(model_or_path, BRepModel):
        model = model_or_path
    elif isinstance(model_or_path, TopoDS_Shape):
        model = index_shape_rbrepmodel(model_or_path)
    else:
        model = load_step_rbrepmodel(model_or_path)

    from .queries import select_region_entities_rdescriptor

    selection = select_region_entities_rdescriptor(
        model,
        entity_ids=entity_ids,
        depth=neighborhood_depth,
    )
    selected_ids = selection["entity_ids"]
    if not selected_ids:
        raise ValueError("No entities were selected for rendering")

    selected_faces = TopTools_IndexedMapOfShape()
    selected_edges: list[TopoDS_Shape] = []
    selected_points: list[tuple[float, float, float]] = []
    for entity_id in selected_ids:
        kind, _, shape = model.resolve_entity(entity_id)
        if kind == "body":
            explorer = TopExp_Explorer(shape, TopAbs_FACE)
            while explorer.More():
                selected_faces.Add(explorer.Current())
                explorer.Next()
        elif kind == "face":
            selected_faces.Add(shape)
        elif kind == "edge":
            selected_edges.append(shape)
        else:
            point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(shape))
            selected_points.append(
                (float(point.X()), float(point.Y()), float(point.Z()))
            )

    face_shapes = [
        selected_faces.FindKey(index)
        for index in range(1, selected_faces.Extent() + 1)
    ]
    highlighted = (
        _mesh_geometry(face_shapes, linear_deflection, angular_deflection)
        if face_shapes
        else None
    )
    highlighted_edges = _edge_geometry(
        selected_edges,
        sample_count=edge_samples,
    )
    highlighted_points = _point_geometry(selected_points)
    return _render_views(
        _mesh_geometry([model.root], linear_deflection, angular_deflection),
        output_path,
        title=f"{title} ({', '.join(selected_ids)})",
        views=views,
        image_size=image_size,
        dpi=dpi,
        context_opacity=0.18,
        highlighted=highlighted,
        highlighted_edges=highlighted_edges,
        highlight_edge_width=highlight_edge_width,
        highlight_point_size=highlight_point_size,
        highlighted_points=highlighted_points,
    )
