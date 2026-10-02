# Two-Stage Herringbone Planetary Reducer Design

## Part Analysis

- Product: compact coaxial two-stage planetary reducer with input and output flanges.
- Envelope target: maximum outside diameter `50 mm`, total height `30 mm` along the reducer axis.
- Power path: input flange -> input shaft -> stage 1 sun -> stage 1 carrier/intermediate shaft -> stage 2 sun -> stage 2 carrier/output shaft -> output flange.
- Gear type: all active mesh gears are herringbone gears to cancel axial thrust and keep the stacked reducer compact.
- Standard parts: herringbone gears, herringbone ring gears, and radial ball bearings come from `simplecadapi.std.gear` and `simplecadapi.std.bearing`.
- Custom solids: housing sleeve, shafts, carriers, and flanges are integrated SimpleCAD solids built from cylinders, boxes, booleans, and tags.

## Structure Analysis

- Stage 1 uses `S1=12`, `P1=18`, `R1=48` teeth, giving fixed-ring planetary reduction `1 + R1 / S1 = 5:1`.
- Stage 2 uses `S2=12`, `P2=12`, `R2=36` teeth, giving fixed-ring planetary reduction `1 + R2 / S2 = 4:1`.
- Total reduction is `5 * 4 = 20:1`.
- Module is `0.75 mm`; stage 1 ring pitch diameter is `36.0 mm` and stage 2 ring pitch diameter is `27.0 mm`.
- Ring rim thickness is `1.90 mm`, keeping the ring outside radii below the `25 mm` product radius limit.
- Gear stack heights are `4.6 mm` per stage, with carrier plates above each gear plane and flanges at the two axial ends.
- The housing is a 50 mm OD sleeve with a large axial clearance bore and connector faces for all coaxial constraints.

## Bearing Analysis

- Input shaft bearing: one radial ball bearing near the input flange.
- Intermediate shaft bearing: one radial ball bearing between stages to locate the stage 1 carrier / stage 2 sun drive shaft.
- Output shaft bearing: one radial ball bearing near the output flange.
- Stage 1 planet bearings: three radial ball bearing placements centered inside the stage 1 planet gears.
- Stage 2 planet bearings: three radial ball bearing placements centered inside the stage 2 planet gears.
- A single reusable `3.2 x 6.6 x 2.0 mm` bearing standard assembly is instanced at all nine friction locations. One definition is placed nine times.
- Bearing assemblies are only placed for location and packaging. Their internal standard-library revolute detail remains visual; no extra reducer-level bearing rotation constraints are added.

## Assembly Plan

- Ground the outer housing and fix both internal ring gears to the housing axis.
- Add revolute constraints for the input shaft, stage 1 carrier, stage 2 carrier, and all six planet axes.
- Fix the stage 1 sun to the input shaft and input flange.
- Fix the stage 2 sun to the stage 1 carrier intermediate shaft.
- Fix the output flange to the stage 2 carrier/output shaft.
- Add external gear constraints from each sun to its planets using `add_gear_constraint_rassembly`.
- Add internal ring-to-planet mesh constraints using same-direction `add_belt_constraint_rassembly` with ring and planet pitch radii.
- Strict solve: every constraint residual must close.

## File Layout

Every part is a marimo notebook with one feature block per cell; the product
is an assembly notebook that composes them with `scad.use`. Shared numbers
and helpers live in plain modules the notebooks import, so the cell cache
tracks them.

| File | Kind | Role |
| --- | --- | --- |
| `compact_two_stage_planetary_reducer.py` | assembly notebook | product: components, bearings, public datums, constraints, strict solve |
| `housing.py` | part notebook | fixed outer housing (`reducer_housing`) |
| `input_flange.py`, `output_flange.py` | part notebooks | rotating end flanges |
| `input_shaft.py` | part notebook | input shaft carrying the stage 1 sun |
| `ring_gear.py`, `sun_gear.py`, `planet_gear.py`, `carrier.py` | part families | one notebook per gear/carrier, used once per stage: `scad.use("planet_gear.py", id="stage2_planet_gear", STAGE="stage2")` |
| `dimensions.py` | plain module | envelope, `StageSpec` / `CarrierSpec` per stage, bearing spec |
| `common.py`, `materials.py` | plain modules | connector, bore and placement helpers; materials |
| `export.py`, `export_mjcf.py` | scripts | product package, AP242 STEP, FCStd; MuJoCo MJCF |

The bearing is `scad.std.bearing.build_ball_bearing(...)`, called once in the
assembly notebook and instanced at all nine seats.

## Validation Assumptions

- The envelope check uses analytical constants: outside diameter `50 mm`, axial span `30 mm`.
- Tooth phasing is visual: each planet instance gets an angular placement so a tooth space is roughly aimed at the sun contact line.
- Gear kinematics are represented by assembly constraints; the static CAD preview remains a positioned assembly, not a dynamic simulation.
- If a boolean union needs one merged part, carrier and shaft cylinders overlap their plates and pads rather than merely touching.
