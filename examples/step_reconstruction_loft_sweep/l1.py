# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "l1"
# revision = "1.0.0"
# ///
"""Rebuild the two-section loft from the L1 STEP analysis evidence."""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- params: measured sections ----
    START_WIDTH, START_HEIGHT = 8.0, 4.0
    END_WIDTH, END_HEIGHT = 3.0, 7.0
    END_CENTER = (1.0, 0.5, 10.0)
    RULED = True
    return END_CENTER, END_HEIGHT, END_WIDTH, RULED, START_HEIGHT, START_WIDTH


@app.cell
def _(END_CENTER, END_HEIGHT, END_WIDTH, RULED, START_HEIGHT, START_WIDTH):
    # ---- feature: variable-section-body (build, profile=geometry) ----
    _sections = [
        scad.make_rectangle_rwire(width=START_WIDTH, height=START_HEIGHT, center=(0.0, 0.0, 0.0)),
        scad.make_rectangle_rwire(width=END_WIDTH, height=END_HEIGHT, center=END_CENTER),
    ]
    variable_section_body = scad.loft_rsolid(profiles=_sections, ruled=RULED)
    print("l1 volume", round(variable_section_body.get_volume(), 6))
    return (variable_section_body,)


@app.cell
def _(variable_section_body):
    l1 = scad.Part(part_id="l1", body=variable_section_body)
    return (l1,)


if __name__ == "__main__":
    app.run()
