# Discipline: Manufacturing Boundaries

**Read when:** you apply default dimensions, or the request touches manufacturability, tolerance, strength or process claims.

What geometric modeling may and may not conclude about manufacturing. Numeric
defaults in this document are first-pass design heuristics, not SDK defaults.

## Evidence labels

- **SDK contract:** canonical length/angle units, product-package/export
  boundaries, and tolerance-analysis APIs.
- **Modeling guidance:** wall thickness, fillet, clearance-hole, and backlash
  starting values. They require user confirmation or an explicit assumption.
  **Unattended:** record the value as an assumption in the brief's ledger (`discipline/operating-modes.md`).

## Defaults are first-pass, not claims

When the user does not specify, these defaults keep a model reasonable — they
are not manufacturability, tolerance, or certification conclusions:

- **SDK contract:** canonical geometry lengths are millimeters and angles are
  degrees; declared units remain part of expression/model data.
- Output geometry: closed, positive-volume solids unless surfaces or
  construction geometry were explicitly requested.
- Small plastic enclosure wall: 2.0–3.0 mm.
- Cosmetic fillet: 1.0–3.0 mm when safe for local geometry.
- M3/M4/M5 normal clearance holes: 3.4/4.5/5.5 mm unless another standard is
  requested.
- Gear mesh backlash starting point: 0.05–0.1 × module — a design decision to
  record, not a hidden constant.

Report which defaults were applied; they are assumptions a reviewer wants to
see.

## What geometry proves

Geometric validation (closure, validity, positive volume, measurements,
solve residuals, replay) proves facts about the model: dimensions,
positions, relationships, kinematic structure. That is the full extent.

## What geometry never proves

Do not claim, from geometry alone:

- structural safety or adequate strength margins
- fatigue life
- thermal performance
- vibration or modal behavior
- tolerance-stack compliance (tolerance analysis must actually run and pass)
- complete manufacturability or DFM sign-off
- process certification or regulatory compliance

These require their own analysis with real inputs. If the user needs them,
say so and route to the appropriate analysis — do not soften the language
into implying them ("should be strong enough" is still a claim).

## When an analysis is run, it ends in a verdict

The boundary above forbids claiming strength without analysis; the
reverse also holds — analysis that was actually run must end in a
judgment, not a table:

- Peak stress vs material allowable (yield/ultimate as appropriate)
  -> state the safety factor, or state that no allowable is available
  and what would establish one.
- Peak displacement vs the functional limit -> pass/fail against the
  requirement the user named, not a bare number.
- Mesh sensitivity stated once; a geometry change that moves a loaded
  region re-runs the comparison before the change is called an
  improvement.

## Format responsibilities

Each export target carries only its own contract
(`../domains/export-and-translation.md`):

- `.scadpkg` is the editable, replayable SimpleCAD boundary — never treat STL
  or OBJ as an editable CAD source.
- STEP carries evaluated BREP and product structure, not feature history.
- STL is facet soup for additive manufacturing; OBJ adds shared vertices for
  DCC exchange. Neither is a validation substitute for the solid.
- MJCF carries simulation kinematics from the constraint graph; it is not a
  manufacturing artifact.

## Dimension hygiene at the manufacturing boundary

- Exposed tunable dimensions are `var()`/`Var` declarations with optional
  unit and tolerance — the tolerance chain that matters downstream should be
  declared, not implied.
- Derived numbers (fits, cumulative offsets, conversions across many
  features) are computed, never freehanded.
- When a tolerance-chain question is the actual task, use the public tolerance
  APIs (`analyze_tolerance`, `check_tolerance`, `ToleranceAnalysis`,
  `ToleranceReport`) and report their output. `check_tolerance` returns a
  check result for a requirement; it does not choose the engineering
  requirement for you.

## Interaction with fabrication processes

Laser/waterjet/CNC handoff questions about 2D profiles, bend lines, and kerf
belong to the downstream fabrication tooling, not to this SDK's geometry
layer; export the geometry that represents the design and let the fabrication
preflight own its process rules. When a design decision affects
fabricability (wall thickness vs part size, hole diameters vs material),
surface it in the report as a flagged assumption rather than silently
optimizing it away.
