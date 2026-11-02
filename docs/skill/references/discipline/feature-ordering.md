# Discipline: Feature Ordering

Operation order is a robustness recommendation, not an SDK-enforced canonical
sequence. Put fragile steps late when that improves diagnosis and repair.

**Read when:** you plan the order of operations of a part, a fillet or chamfer fails, or you pattern a feature or loft sections.

## Evidence labels

- **SDK contract:** documented operation results and failure behavior.
- **Modeling guidance:** recommended source organization; other valid operation
  orders remain possible when the resulting inputs are valid.

## Recommended first-pass order

```text
base solid
→ major additive features
→ subtractive features (openings, pockets)
→ shell
→ through-wall holes
→ fillets and chamfers last
```

Why: fillets are often failure-prone, and boolean/detail operations may change
the topology used by later selections. Postponing fragile details often keeps
the model easier to repair; it is not a mandatory SDK ordering rule.

## Boolean tool geometry

- **Modeling guidance: overshoot through-cut tools.** Extend cutting tools past
  the faces they enter and exit. The amount is part-scale and design-dependent;
  `1 mm` is not an SDK default or guarantee. Coincident or coplanar
  tool/target faces are a common kernel failure mode.
- **Modeling guidance:** combine identical repeated cuts when convenient;
  validate one representative before patterning.
- `union_rsolid` has a one-manifold-`Solid` result contract and fails when it
  cannot produce one. Face-area contact or positive-volume overlap can work;
  edge-, vertex-, and tangent-only contact cannot satisfy that contract.
- `cut_rsolid(..., skip_non_intersecting=False)` makes non-intersecting tools
  fail instead of being silently skipped. Treat this as a strict diagnostic
  mode; whether a skipped tool is acceptable is a workflow decision.

## Selecting what to fillet

- Radius must fit the local geometry: when a profile cannot accept the
  nominal radius, reduce it, narrow the edge selection, or move the operation
  later. This SDK's fillet fails explicitly (`ValueError: Fillet failed`) —
  there is no silent radius fallback, so treat any failure as a signal to
  change radius, selection, or order.
- Filter selected edges by feature intent; split edge groups by feature
  rather than filleting everything at once.
- Prefer robust selections (tags, axes, normals, positions, QL predicates)
  over topology indexes; booleans and fillets renumber topology.

## Patterns

- Verify equal spacing/angles on at least two units before patterning
  (`linear_pattern_rsolidlist`, `radial_pattern_rsolidlist`); repetition is a
  hypothesis until measured.
- Pattern after the prototype feature validates; never pattern an unvalidated
  feature to hide a defect.

## Structure the source to localize failure

Each feature is a named step — a per-feature function or a distinct
intermediate variable — so a failed operation names one feature, and a
parameter change touches one obvious place. Print a small QL-derived fact
after each major step (counts, centers, volume) so drift is caught at the
step that caused it.

## Complex surfaces

- `loft_rsolid` accepts `Wire`/`Vertex` sections and the implementation enables
  OCCT compatibility checking. **Modeling guidance:** keep corresponding wire
  sections topologically compatible (same edge count and meaningful feature
  boundaries). Compatibility checking is not a substitute for authoring
  corresponding sections or validating the resulting solid.
- When authoring wires from sampled data, sample along common rails so each
  section places the same feature at the same edge. Cluster samples toward
  feature lines or regions where curvature changes fastest.
- Interpolation choice matters: a curve that is flat at each control point
  (zero derivative at both ends of every interval) can put a crease at every
  knot; measurement noise in control curves can become visible surface ripple.
  Smooth control data before lofting through it.
- Use `track_section_contours_rdescriptor` evidence when section topology
  changes across stations (birth/death/split/merge); do not force a
  topology-changing sequence into one global loft.
