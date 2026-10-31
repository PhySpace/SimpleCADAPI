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
