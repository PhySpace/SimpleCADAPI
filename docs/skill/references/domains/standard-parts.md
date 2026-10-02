# Task Domain: Standard Parts

Use the parameterized standard-library factories before hand-modeling standard
mechanical components.

## Use when

- The request names gears, ring gears, racks, cycloidal discs, or ball
  bearings, or a mechanism built from them (reducers, gearboxes, actuators).
- A part definition needs a durable standard-component building block.

## Do not use

- Substantial custom geometry beyond the factory parameters: switch to
  `domains/part-modeling.md` and model it explicitly.
- Sourcing purchasable off-the-shelf STEP files: that is an external catalog
  task, not this SDK.

## Import surface

```python
import simplecadapi as scad

gear = scad.std.gear.make_spur_gear_rsolid(n_teeth=24, module=1.5, gear_height=8.0)
ring = scad.std.gear.make_spur_ring_gear_rsolid(
    n_teeth=72, module=1.5, gear_height=8.0, rim_thickness=4.0,
    backlash=0.08 * 1.5,
)
rack = scad.std.gear.make_spur_rack_rsolid(module=1.5, n_teeth=18)
bearing = scad.std.bearing.make_ball_bearing_rassembly(
    bore_diameter=8.0, outer_diameter=22.0, bearing_width=7.0, ball_diameter=3.5,
)
```

Direct submodule import is also supported
(`from simplecadapi.std.gear import make_spur_gear_rsolid`). Always use keyword
arguments.

## Factory catalog

Read `references/docs/stdlib/README.md` for the index and the exact page
`references/docs/stdlib/<function_name>.md` before calling any factory:

- External gears: `make_spur_gear_rsolid`, `make_helical_gear_rsolid`,
  `make_herringbone_gear_rsolid`, `make_straight_bevel_gear_rsolid`.
- Internal ring gears: `make_spur_ring_gear_rsolid`,
  `make_helical_ring_gear_rsolid`, `make_herringbone_ring_gear_rsolid`
  (helical/herringbone ring gears are built by direct multi-loop sweep).
- Racks: `make_spur_rack_rsolid`, `make_helical_rack_rsolid`,
  `make_herringbone_rack_rsolid`.
- Cycloidal discs: `make_cycloidal_disc_rsolid`.
- Bearings: `make_ball_bearing_rassembly` returns a product `Assembly`;
  `build_ball_bearing` is the durable sub-assembly builder (keyword-only
  parameters, plus `revision` and `ground` — default `ground="outer_ring"`)
  for `@scad.assemble` definitions with explicit bearing instances.

## Integration rules

- Standard parts return normal shapes or product assemblies: transform, tag,
  assemble, and export them like any other geometry.
- Mesh discipline: for a gear/ring pair, consistent `module`, center distance
  derived from tooth counts, and explicit `backlash` (typical starting point
  `0.05-0.1 * module`) are part of the design, not afterthoughts.
- Prefer `build_ball_bearing` over rebuilding bearings by hand inside product
  definitions; a parent assembly references it as one nested definition.

## Validation gates

- Verify tooth counts, module, center distances, and overall bounding boxes
  with QL measurements after assembly.
- For gear meshes, confirm the intended kinematic constraint
  (`add_gear_constraint_rassembly`) references the correct axes and ratio.
- Check bearing bore/outer diameters against the mated shaft and housing
  geometry before final capture.

## Failure modes

- Backlash omitted or defaulted badly: mesh locks or interferes; set backlash
  explicitly for ring-gear pairs.
- Bevel gear orientation: measure `make_straight_bevel_gear_rsolid` output
  axes and faces with `ql` before constraining; do not assume the factory's
  mounting orientation.
