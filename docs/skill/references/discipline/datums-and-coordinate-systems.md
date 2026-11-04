# Discipline: Datums and Coordinate Systems

Choosing origins, planes, and axes from function before the first primitive.
The coordinate and unit statements below are SDK facts where labeled; origin
choices and part-type defaults are modeling guidance.

**Read when:** before the first primitive of a part or assembly, when choosing an origin, base plane or up axis, or when placing imported or factory geometry.

## Core rule

The part-local coordinate system is chosen from the functional datum, and the
SDK evaluates lengths in millimeters and angles in degrees (declared units are
preserved in model JSON). Declaring the convention in the brief is not
optional bookkeeping: every downstream measurement, connector frame, and
placement reads against it.

## Modeling guidance: origin defaults by part type

- **Symmetric standalone parts**: origin at the body center.
- **Plates / mounting plates**: origin at footprint center; thickness along
  the up axis.
- **Enclosures**: origin at footprint center; base/lid mating surfaces
  controlled by named height parameters.
- **Shafts, knobs, axisymmetric parts**: origin on the rotational axis.
- **Adapter / mating plates**: origin on the primary mounting datum or the
  bolt-pattern center.

When nothing better applies, center of the main part or assembly.

## Convention skeleton

Declare in the brief:

```text
Origin: center | base datum | mounting interface | functional axis
Base plane: which model plane carries the main profile
Up / feature direction: which axis, which sign
Named dimensions: offsets, spacings, clearances
Datum features: mating faces, screw axes, centerlines, locating features
```

`SimpleWorkplane` (a context manager for modeling in a local frame) and
`CoordinateSystem` exist for local contexts; use them when a feature is
naturally authored in a local frame, and say so in the source.

## Workplanes from the model (SDK facts)

A datum that comes from geometry is a recorded workplane, not copied numbers:
`make_workplane_from_face_rworkplane` (a planar face, optional `offset`, `x_edge`,
`flip`), `make_workplane_from_points_rworkplane` (three vertices or points),
`make_workplane_from_axis_rworkplane` (an edge or a hole's axis, turned by `angle`),
`make_workplane_midplane_rworkplane` (two parallel faces: a symmetry plane) and
`make_workplane_normal_to_curve_rworkplane` (a sweep profile's plane at a fraction of
a path). See `references/docs/core/simple_workplane.md`.

- Give the workplane its own name in its own cell (`wp_top = ...`), then sketch on it
  (`make_sketch_rsketch(..., plane=wp_top)`) or model in it (`with wp_top:`). A later
  cell may enter it again; it is cached with its cell.
- A sketch or feature on a workplane made from a face follows the face when the
  model changes (the notebook re-runs it; a model-JSON replay rebuilds the frame
  from the recorded op). Copying `wp.origin` / `wp.normal` into literals breaks that
  link: use the workplane value.
- Name the datum in the brief like any other: "boss sketch on `wp_top` (top face of
  base), x along the long edge".

## Placement semantics

- Part-local coordinates equal the wrapped solid's modeling coordinates. If a
  different part origin is wanted, build the solid in that frame before
  wrapping it as a `Part`.
- A component placement maps child-local coordinates into parent coordinates;
  nested placements compose. Moving a part inside an assembly changes only
  the placement — never the part's internal solid.
- A numeric placement should correspond to a stated datum, offset, clearance,
  axis, or contact relationship. An untraceable transform constant is the
  same defect as a magic number.

## Imported and factory geometry

Geometry you did not author — stdlib factory output, imported STEP — carries
no assumed origin or orientation. Measure it (QL queries on faces, axes,
bounds; `inspect.brep` for STEP) and derive connector frames from measured
geometry. Bevel gears are the classic trap: measure the output axes before
constraining.

## Validation

- Frame checks: expected axes aligned with model axes; repeated parts share
  orientation; mating frames land where the brief says.
- After assembly: verify flush faces measure flush, axes measure coaxial, and
  offsets measure as specified — see `geometric-validation.md`.
