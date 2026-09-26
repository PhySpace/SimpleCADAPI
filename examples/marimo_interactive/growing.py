import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell
def _():
    return


@app.cell
def _():
    import math
    import sys
    from pathlib import Path

    import marimo as mo
    import simplecadapi as scad
    from simplecadapi import ql

    sys.path.insert(0, str(Path(__file__).parent))
    import live_runtime

    # One registration owns the session, tessellation, the direct geometry
    # channel to the Studio viewport, and optional durable package export.
    LIVE = live_runtime.register(out_dir=Path(__file__).parent / "out")

    PCD = 78.0  # bolt-circle diameter, fixed in this demo


    def make_cyl(radius, height, bottom_z, x=0.0, y=0.0):
        return scad.make_cylinder_rsolid(
            radius=radius, height=height,
            bottom_face_center=(x, y, bottom_z), axis=(0.0, 0.0, 1.0))

    return LIVE, PCD, make_cyl, math, mo, ql, scad


@app.cell
def _(mo):
    flange_od = mo.ui.slider(96, 140, value=100, step=1, label="flange OD mm")
    flange_t = mo.ui.slider(5, 25, value=10, step=0.5, label="flange thickness mm")
    hub_od = mo.ui.slider(35, 64, value=55, step=1, label="hub OD mm")
    hub_top = mo.ui.slider(12, 45, value=30, step=1, label="hub top z mm")
    bore_d = mo.ui.slider(10, 50, value=30, step=1, label="bore D mm")
    bolt_d = mo.ui.slider(6, 12, value=11, step=0.5, label="bolt hole D mm")
    bolt_n = mo.ui.number(3, 12, value=6, step=1, label="bolt count")
    mo.vstack([flange_od, flange_t, hub_od, hub_top, bore_d, bolt_d, bolt_n])
    return bolt_d, bolt_n, bore_d, flange_od, flange_t, hub_od, hub_top


@app.cell
def _(flange_od, flange_t, make_cyl):
    # ---- feature: flange-disc (build) ----
    body_disc = make_cyl(flange_od.value / 2, flange_t.value, 0.0)
    return (body_disc,)


@app.cell
def _(body_disc, hub_od, hub_top, make_cyl, scad):
    # ---- feature: hub-boss (add) ----
    body_hub = scad.union_rsolid(body_disc, make_cyl(hub_od.value / 2, hub_top.value, 0.0))
    return (body_hub,)


@app.cell
def _(body_hub, bore_d, hub_od, hub_top, make_cyl, scad):
    # ---- feature: center-bore (subtract) ----
    body_bore = scad.cut_rsolid(
        body_hub,
        make_cyl(min(bore_d.value, hub_od.value - 8.0) / 2, hub_top.value + 2.0, -1.0),
    )
    return (body_bore,)


@app.cell
def _(PCD, body_bore, bolt_d, bolt_n, flange_t, make_cyl, math, scad):
    # ---- feature: bolt-holes (subtract) ----
    body_bolts = scad.cut_rsolid(body_bore, [
        make_cyl(bolt_d.value / 2, flange_t.value + 2.0, -1.0,
                 x=PCD / 2 * math.cos(math.tau * i / bolt_n.value),
                 y=PCD / 2 * math.sin(math.tau * i / bolt_n.value))
        for i in range(int(bolt_n.value))
    ])
    return (body_bolts,)


@app.cell
def _(body_bolts, flange_t, hub_od, math, ql, scad):
    # ---- feature: hub-root-fillet (modify, only when geometry admits it) ----
    circle = 2.0 * math.pi * hub_od.value / 2
    chain = (
        ql.edges()
        .where(ql.prop("geom.type", "==", "CIRCLE"))
        .where(ql.prop("geom.center.z", ">=", flange_t.value - 0.5))
        .where(ql.prop("geom.center.z", "<=", flange_t.value + 0.5))
        .where(ql.prop("geom.length", ">=", circle * 0.9))
        .where(ql.prop("geom.length", "<=", circle * 1.1))
    )
    if len(chain.resolve(body_bolts)) == 1:
        body = scad.fillet_rsolid(
            solid=body_bolts, edges=chain.exactly(1),
            radius=3.0, generated_faces_tag="fillet.hub_root")
    else:
        body = body_bolts
    return (body,)


@app.cell
def _(LIVE, mo):
    reset_button = mo.ui.button(
        label="delete live file (empty the viewport)",
        on_change=lambda _click: LIVE.reset(),
    )
    mo.hstack([reset_button, mo.md("click to empty the Studio viewport")])
    return


@app.cell
def _(LIVE, body):
    last = LIVE.last
    _ = body  # dataflow dependency: refresh after the final step
    import plotly.graph_objects as go

    last = LIVE.last
    fig = go.Figure(go.Mesh3d(
        x=[p[0] for p in last.mesh.positions],
        y=[p[1] for p in last.mesh.positions],
        z=[p[2] for p in last.mesh.positions],
        i=list(last.mesh.indices[0::3]),
        j=list(last.mesh.indices[1::3]),
        k=list(last.mesh.indices[2::3]),
        color="#8fb4d9",
        flatshading=True,
        lighting=dict(ambient=0.55, diffuse=0.8, specular=0.4, roughness=0.5),
    ))
    fig.update_layout(
        height=540,
        margin=dict(l=0, r=0, t=30, b=0),
        paper_bgcolor="#0b0e12",
        font=dict(color="#dfe7f1"),
        title=f"{last.step} - volume {last.volume:,.1f} mm3 - {last.faces} faces",
        scene=dict(
            bgcolor="#0b0e12",
            aspectmode="data",
            camera=dict(eye=dict(x=1.9, y=1.6, z=1.2), up=dict(x=0, y=0, z=1)),
        ),
    )
    fig
    return


if __name__ == "__main__":
    app.run()
