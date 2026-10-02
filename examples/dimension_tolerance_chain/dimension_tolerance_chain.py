# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "dimension_tolerance_chain"
# revision = "1.0.0"
# ///
"""Declare, propagate and validate a dimension tolerance chain.

A housing holds a bearing and a spacer; the axial clearance left over is the
closing link of the chain. Its tolerance follows from the three toleranced
inputs and must stay inside the clearance requirement. The housing body is a
box spanning the housing dimension, so the chain drives real geometry.

    sca run examples/dimension_tolerance_chain/dimension_tolerance_chain.py
    uv run python examples/dimension_tolerance_chain/report.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- params ----
    housing_span = scad.var(
        name="housing_span", default=100.0, unit="mm", tolerance=0.15,
        comment="Internal housing span")
    # Declared in cm with a mm tolerance: the chain converts units.
    bearing_width = scad.var(
        name="bearing_width", default=2.0, unit="cm",
        tolerance=(-0.04, 0.05), tolerance_unit="mm", comment="Bearing width")
    spacer_width = scad.var(
        name="spacer_width", default=79.4, unit="mm", tolerance=0.05,
        comment="Spacer width")
    return bearing_width, housing_span, spacer_width


@app.cell
def _(bearing_width, housing_span, spacer_width):
    # ---- feature: axial-clearance (chain) ----
    # The closing link. The requirement is held by a variable: the cell cache
    # stores variables only, and the product's definition takes the
    # requirements the notebook's variables hold.
    axial_clearance = housing_span - bearing_width - spacer_width
    axial_clearance_req = scad.get_active_session().require_tolerance(
        value=axial_clearance, tolerance=(-0.25, 0.24), tolerance_unit="mm",
        method="worst_case", name="axial_clearance")
    scad.get_active_session().validate_tolerances(raise_on_failure=True)
    worst_case = scad.analyze_tolerance(value=axial_clearance, method="worst_case")
    rss = scad.analyze_tolerance(value=axial_clearance, method="rss")
    return axial_clearance, axial_clearance_req, rss, worst_case


@app.cell
def _(housing_span):
    # ---- feature: housing (build) ----
    housing = scad.make_box_rsolid(
        width=housing_span, height=10.0, depth=10.0,
        tag_prefix="tolerance_chain.housing",
        result_tag="part.tolerance_chain.housing")
    return (housing,)


@app.cell
def _(housing):
    dimension_tolerance_chain = scad.make_part_rpart(
        part_id="dimension_tolerance_chain", body=housing,
        name="Dimension tolerance chain housing")
    return (dimension_tolerance_chain,)


if __name__ == "__main__":
    app.run()
