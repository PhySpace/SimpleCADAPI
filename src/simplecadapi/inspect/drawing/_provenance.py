"""Versioned identities and explicit coordinate transforms for evidence."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np

RESULT_VERSION = "2.2"


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def file_hash(path) -> str:
    with Path(path).open("rb") as stream:
        checksum = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def page_metadata(path, page) -> dict:
    return {
        "result_version": RESULT_VERSION,
        "source_id": file_hash(path),
        "source": str(Path(path).resolve()),
        "coordinate_space": "page_display",
        "units": "pt",
        "page": page.number,
        "rotation": page.rotation,
        "media_box": list(page.mediabox),
        "crop_box": list(page.cropbox),
        "page_rect": list(page.rect),
        "storage_to_display": list(page.rotation_matrix),
        "display_to_storage": list(page.derotation_matrix),
        "pdf_engine_version": __import__("pymupdf").__version__,
    }


def pixel_transform(scale, x, y) -> dict:
    """Pixel edges, with integer pixmap origin (not requested crop origin)."""
    forward = [[scale, 0.0, -x], [0.0, scale, -y], [0.0, 0.0, 1.0]]
    return {
        "page_to_pixel": forward,
        "pixel_to_page": np.linalg.inv(forward).tolist(),
        "pixel_origin": [x, y],
        "actual_origin_pt": [x / scale, y / scale],
        "pixel_convention": "edges; pixel centers are (column+0.5,row+0.5)",
    }


def model_metadata(model) -> dict:
    from simplecadapi._cpp.occt.BRepTools import BRepTools
    from simplecadapi._cpp.occt.TopTools import TopTools_FormatVersion
    from ..brep.queries import _model

    indexed = _model(model)
    buffer = io.BytesIO()
    BRepTools.Write_s(
        indexed.root,
        buffer,
        False,
        False,
        TopTools_FormatVersion.TopTools_FormatVersion_VERSION_3,
    )
    model_hash = hashlib.sha256(buffer.getvalue()).hexdigest()
    return {
        "result_version": RESULT_VERSION,
        "source_id": model_hash,
        "model_hash": model_hash,
        "hash_method": "BREP-v3-without-triangulation",
        "source_file_hash": (
            file_hash(model) if isinstance(model, (str, Path)) else None
        ),
        "coordinate_space": "section_local",
        "units": "mm",
    }
