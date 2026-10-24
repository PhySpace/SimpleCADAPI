"""Render a saved geometric-feature catalog without rerunning recognition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .feature_catalog import FEATURE_CATEGORIES, _target_hash
from .manufacturing import ModelInput, _model


FEATURE_COLORS = {
    "extrusion": (41 / 255, 173 / 255, 87 / 255),
    "revolution": (6 / 255, 182 / 255, 212 / 255),
    "loft": (236 / 255, 72 / 255, 153 / 255),
    "sweep": (79 / 255, 70 / 255, 229 / 255),
    "hole": (148 / 255, 61 / 255, 199 / 255),
    "fillet": (239 / 255, 68 / 255, 68 / 255),
    "chamfer": (242 / 255, 177 / 255, 52 / 255),
    "sheet_metal": (59 / 255, 130 / 255, 246 / 255),
    "sheet_metal_bend": (249 / 255, 115 / 255, 22 / 255),
}

_LABELS = {
    "extrusion": "Extrusion-style geometry",
    "revolution": "Revolution-style geometry",
    "loft": "Loft-style geometry",
    "sweep": "Sweep-style geometry",
    "hole": "Holes",
    "fillet": "Fillets",
    "chamfer": "Chamfers",
    "sheet_metal": "Sheet-metal bodies",
    "sheet_metal_bend": "Sheet-metal bends",
}


def _load_report(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError(f"feature_report does not exist: {path}")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise TypeError("feature_report JSON root must be an object")
    return result


def _style_key(feature: Mapping[str, Any]) -> str:
    if (
        feature.get("category") == "sheet_metal"
        and feature.get("subtype") == "cylindrical_bend"
    ):
        return "sheet_metal_bend"
    return str(feature.get("category"))


def render_geometric_features_rpath(
    model_or_path: ModelInput,
    feature_report: Mapping[str, Any] | str | Path,
    output_path: str | Path,
    *,
    views: Sequence[tuple[float, float, str]] | None = None,
    image_size: tuple[float, float] = (18.0, 12.0),
    dpi: int = 180,
    linear_deflection: float = 0.12,
    angular_deflection: float = 0.18,
) -> Path:
    """Render the supplied feature report with the approved category palette.

    The function consumes a report dictionary or saved ``feature-index.json``.
    It never invokes feature recognition. It verifies the target hash and every
    highlighted entity ID before rendering so the image cannot silently drift
    from the authoritative per-instance catalog.
    """

    model = _model(model_or_path)
    report = _load_report(feature_report)
    if report.get("target_sha256") != _target_hash(model, model_or_path):
        raise ValueError("feature_report target_sha256 does not match model_or_path")
    features = report.get("features")
    if not isinstance(features, list):
        raise TypeError("feature_report.features must be a list")
    grouped: dict[str, list[str]] = {key: [] for key in FEATURE_COLORS}
    for feature in features:
        if not isinstance(feature, Mapping):
            raise TypeError("every feature_report.features item must be an object")
        category = feature.get("category")
        if category not in FEATURE_CATEGORIES:
            raise ValueError(f"unsupported feature category in report: {category}")
        ids = feature.get("highlight_entity_ids")
        if not isinstance(ids, list) or not ids:
            raise ValueError(
                f"feature {feature.get('feature_id')} has no highlight_entity_ids"
            )
        for entity_id in ids:
            kind, _, _ = model.resolve_entity(str(entity_id))
            if kind != "face":
                raise ValueError(
                    f"feature {feature.get('feature_id')} highlight is not a face: "
                    f"{entity_id}"
                )
        grouped[_style_key(feature)].extend(str(value) for value in ids)
    from .render import (
        DEFAULT_VIEWS,
        _edge_polydata,
        _mesh_polydata,
        _render_polydata_views,
    )

    groups = []
    legend = []
    for style_key in (
        "sheet_metal",
        "sheet_metal_bend",
        "extrusion",
        "revolution",
        "loft",
        "sweep",
        "hole",
        "fillet",
        "chamfer",
    ):
        ids = sorted(
            set(grouped[style_key]), key=lambda value: int(value.split(":", 1)[1])
        )
        if not ids:
            continue
        shapes = [model.resolve_entity(entity_id)[2] for entity_id in ids]
        color = FEATURE_COLORS[style_key]
        groups.append(
            (
                _mesh_polydata(shapes, linear_deflection, angular_deflection),
                color,
                1.0,
            )
        )
        legend.append((_LABELS[style_key], color))
    if not groups:
        raise ValueError("feature_report contains no highlightable feature faces")
    return _render_polydata_views(
        _mesh_polydata([model.root], linear_deflection, angular_deflection),
        output_path,
        title="BREP geometric-feature catalog",
        views=tuple(views or DEFAULT_VIEWS),
        image_size=image_size,
        dpi=dpi,
        context_opacity=0.16,
        brep_edge_polydata=_edge_polydata([model.root], deflection=linear_deflection),
        highlighted_groups=groups,
        legend=legend,
        legend_columns=1,
        legend_panel=True,
    )


__all__ = ["FEATURE_COLORS", "render_geometric_features_rpath"]
