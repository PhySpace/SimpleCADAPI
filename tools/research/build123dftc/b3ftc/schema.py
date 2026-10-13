"""Versioned, portable feature trace contract."""
SCHEMA_VERSION = "1.0"


def empty_trace():
    return {"schema_version": SCHEMA_VERSION, "steps": [], "result_refs": [],
            "b3d_status": "ok", "b3d_volume": None, "b3d_bbox": None,
            "solid_count": 0, "unsupported": [], "error": ""}
