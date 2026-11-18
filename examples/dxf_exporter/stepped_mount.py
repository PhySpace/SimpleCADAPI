# /// script
# requires-python = ">=3.12"
# dependencies = ["simplecadapi==2.3.0.post1"]
# [tool.simplecadapi]
# id = "stepped-mount"
# kind = "part"
# ///

import marimo

app = marimo.App()


@app.cell
def _():
    import simplecadapi as scad

    return (scad,)


@app.cell
def _(scad):
    # ---- params: hole pattern ----
    HOLE_DIAMETER = scad.var("hole_diameter", 6.0, unit="mm")
    HOLE_PITCH = scad.var("hole_pitch", 31.0, unit="mm")
    return HOLE_DIAMETER, HOLE_PITCH


@app.cell
def _(scad):
    # ---- params: ledge ----
    LEDGE_THICKNESS = scad.var(
        "ledge_thickness", 8.0, unit="mm", tolerance=(-0.05, 0.10)
    )
    TOOL_CLEARANCE = 4.0
    return LEDGE_THICKNESS, TOOL_CLEARANCE


@app.cell
def _(HOLE_DIAMETER, HOLE_PITCH, LEDGE_THICKNESS, TOOL_CLEARANCE, scad):
    blank = scad.make_box_rsolid(width=80, height=50, depth=12)
    cutter = scad.make_box_rsolid(
        width=24, height=52, depth=12, bottom_face_center=(32, 0, LEDGE_THICKNESS)
    )
    body = scad.cut_rsolid(blank, cutter, on_split="error")
    for x in (-23, -23 + HOLE_PITCH):
        tool = scad.make_cylinder_rsolid(
            radius=HOLE_DIAMETER / 2,
            height=12 + 2 * TOOL_CLEARANCE,
            bottom_face_center=(x, 3, -TOOL_CLEARANCE),
        )
        body = scad.cut_rsolid(body, tool, on_split="error")
    part = scad.make_part_rpart(part_id=scad.notebook_id(), body=body)
    return (part,)


@app.cell
def _(HOLE_DIAMETER, HOLE_PITCH, LEDGE_THICKNESS):
    hole_a = {
        "cylinder": {
            "axis_point": [-23, 3, 6],
            "axis": [0, 0, 1],
            "radius_mm": float(HOLE_DIAMETER) / 2,
        }
    }
    hole_b = {
        "cylinder": {
            "axis_point": [-23 + float(HOLE_PITCH), 3, 6],
            "axis": [0, 0, 1],
            "radius_mm": float(HOLE_DIAMETER) / 2,
        }
    }
    lower_plane = {"plane": {"point": [30, 0, 0], "normal": [0, 0, 1]}}
    ledge_plane = {
        "plane": {"point": [30, 0, float(LEDGE_THICKNESS)], "normal": [0, 0, 1]}
    }
    DRAWING_INTENT = {
        "dimensions": [
            {
                "parameter": "HOLE_DIAMETER",
                "view": "front",
                "semantic": "diameter",
                "of": hole_a,
                "fit": "H7",
                "at": 155,
                "out": 12,
            },
            {
                "parameter": "HOLE_PITCH",
                "view": "front",
                "semantic": "linear",
                "between": [hole_a, hole_b],
                "axis": "x",
                "side": "top",
            },
            {
                "parameter": "LEDGE_THICKNESS",
                "view": "top",
                "semantic": "linear",
                "between": [lower_plane, ledge_plane],
                "axis": "y",
                "side": "right",
                "use_parameter_tolerance": True,
            },
        ],
    }
    return (DRAWING_INTENT,)


if __name__ == "__main__":
    app.run()
