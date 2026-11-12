# Discipline: Mechanical Modeling

**Read when:** you choose a construction strategy or decompose a mechanical part or product before selecting SimpleCADAPI operations.

How to choose a construction strategy before selecting SimpleCADAPI operations.
This document separates SDK contracts from mechanical design guidance.

## Evidence labels

- **SDK contract** means behavior verified in the public API or generated API
  documentation.
- **Modeling guidance** is an engineering recommendation. The SDK does not
  infer manufacturing intent, strength, fit, or optimal feature order from it.

## Decide the construction before writing geometry

- **Make the spec's controlling dimensions direct named parameters.**
  Profile-driven shapes get one closed profile plus extrude/revolve/sweep/
  loft; block-and-feature parts get a base solid plus subtractive features.
  Choose whichever lets the user's dimensions appear as parameters instead of
  derived values.
- **Decide part vs assembly before modeling.** Bodies that are separately
  manufactured, purchased, or movable belong in an assembly with connectors
  and placements; monolithic manufacturing intent gets a single fused solid.
  A Part holds exactly one solid: several solids that belong together are one
  Part per solid in an Assembly (identity placements if they only sit side by
  side). Never leave stray solids (tools, construction) out of the product where
  one labeled product was intended.
- **Pick the origin and orientation from the functional datum** — the mating
  interface, mounting plane, or symmetry axis — not from wherever the first
  primitive happened to land. See `datums-and-coordinate-systems.md`.
- **Model the part as a sequence of intentional operations**, not one opaque
  final shape: each feature is a named step, so a failed operation points at
  exactly one feature and a parameter change touches one obvious place.

## Build from low to high dimensionality

```text
Vertex / Edge / Wire / Face profiles
→ Solid features: extrude, revolve, sweep, loft
→ booleans for openings and merged bodies
→ detail: fillets, chamfers, shells last
```

**SDK contract:** keep replayable modeling operations in public API calls such as
`make_circle_rface`, `extrude_rsolid`, `cut_rsolid`, and `fillet_rsolid`; use
keyword arguments for documented public APIs. The SDK records graph operations
when a `GraphSession` is active, but it does not require every local helper to
be a one-line public call.

## Distinguish physical roles

- **Monolithic part**: one manufactured body, one fused solid.
- **Independent manufactured part**: own file, own `Part`, placed in the
  assembly.
- **Purchased/standard component**: stdlib factory or imported geometry with
  measured interfaces; never re-modeled by hand when a factory exists.
- **Motion component**: interfaces expressed as connectors; relations as
  declarative constraints (revolute/prismatic/gear/rack-pinion/belt).

## Parameters are design intent

- Every meaningful dimension is a named parameter in the file that consumes
  it; no magic numbers buried inside geometry calls.
- Exposed tunable parameters are `var()`/`Var` declarations (optionally with
  unit and tolerance); everything else is a plain constant in place.
- Numbers that are the result of computation (centers, radii from fits,
  cumulative offsets) are computed, never freehanded.

## Fastener envelopes precede geometry

When the part has fastened or mating features, derive the controlling
minimums before modeling and carry them as named parameters in the
brief — they are inputs, not patches after an interference check
fails:

- Countersink/counterbore: head diameter + shaft + wall/clearance ->
  minimum land diameter, minimum boss thickness, minimum edge distance.
- Insertion path: envelope swept along the assembly motion -> minimum
  lateral offset between the path and any neighboring material
  (e.g. rod-root offset >= head radius + rod radius + wall).
- The envelope that guarantees assemblability usually must also machine
  the clearance: design it as a cutting feature, and keep the check on
  its result rather than on the posture alone.

## Sanity-check proportions before generating

Compare the expected bounding box against the real-world object, wall
thickness against overall size, feature positions against edges and
neighbors. Order-of-magnitude and collision errors pass geometric validation
and fail only at review — catch them in the brief.

## What geometry cannot tell you

A valid, closed, positive-volume solid says nothing about strength, fatigue,
thermal behavior, vibration, tolerance compliance, or regulatory fitness.
Do not claim any of those without the corresponding analysis having actually
run. See `manufacturing-boundaries.md`.
