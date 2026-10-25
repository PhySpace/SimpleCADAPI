# Discipline: Failure and Repair

The loop for generation, solve, export, or validation failures. API behavior is
marked as contract; diagnosis heuristics are marked as modeling guidance.

## Evidence labels

- **SDK contract** is limited to behavior exposed by the public API or reports.
- **Modeling guidance** suggests a repair path; validate it against the actual
  failure and do not present it as an automatic SDK rule.

## The loop

1. Read the failing output — the exception, the report, the residual, the
   comparison summary. Name what failed before changing anything.
2. Classify the failure (classes below).
3. Make the smallest responsible source or parameter change.
4. Re-run the failed command.
5. Re-run dependent validation.
6. Report remaining risk or deliberate deviations.

Never suppress the symptom: no exception swallowing, no special-cased input,
no patching exported or solved artifacts.

## Failure classes
### Boolean failure

- Verify valid operands and the intended intersection/contact. For union, the
  SDK can produce one solid from finite-area face contact or positive-volume
  overlap; edge-, vertex-, and tangent-only contact cannot satisfy the
  one-manifold-solid contract.
- **Modeling guidance:** remove accidental tangency or coincident terminal
  faces by extending through-cut tools beyond the target faces.
- Isolate and simplify the failing base/tool pair.
- `cut_rsolid(..., skip_non_intersecting=False)` is the strict diagnostic mode;
  with the default `True`, non-intersecting tools may be ignored.
- `cut_rsolid` expected a single Solid but the kernel returned several: the cut
  split the body. If that is intended, call `cut_rsolid_list`; if not, the tool
  crosses the body completely or touches a wall tangentially — resize or
  reposition it.
- After repeated failure, reconsider operation order — not just retry the same
  cut harder.

### Union returns multiple bodies

`union_rsolid` requires a one-manifold-`Solid` result and fails if it cannot
produce one. If the design is one body, use a contact or overlap that is
topologically capable of producing one solid, then recompute. If the design is
actually multiple parts, the answer is an assembly, not a union.

### Fillet/chamfer failure

The following combines the SDK's explicit fillet failure behavior with
modeling guidance for narrowing the cause.
- Radius exceeds local geometry → reduce the radius, narrow the edge
  selection, or move the operation later. The public fillet implementation
  fails explicitly when the kernel build is not done; it does not silently
  choose a smaller radius.
- Unintended tiny edges in the selection → filter by feature intent and split
  edge groups rather than filleting everything at once.
- Complex post-boolean topology → apply fillets later in the source order and
  re-select edges using stable geometry or tags.

### Loft/sweep/complex-surface failure

The following are modeling and diagnosis guidance, not guarantees of every
OCCT or SimpleCADAPI loft result.

- **Modeling guidance:** bracket the failure with increasing prefixes and
  adjacent section pairs; watch reported volume as well as the exception. An
  absurd volume is already a failure signal. If every adjacent pair succeeds
  but the full set fails, inspect sample count, correspondence, and section
  ordering.
- A disconnected section with multiple closed regions can produce a plausible
  but unusable result. End the loft at the last connected station, or bridge
  and cut back afterwards; confirm the result with volume and BREP/topology
  diagnostics.
- Keep the section sample/edge structure intentional. If a component does not
  exist at one station, do not silently drop its sample when correspondence
  depends on a fixed count; carry a defined value or split the construction.
- A section topology change across stations (birth/death/split/merge) is a
  reason to inspect `brep.track_section_contours_rdescriptor` and consider
  splitting the loft; this is a diagnosis strategy, not a guarantee that one
  global loft must fail.
- A boolean against a large freeform surface can be expensive in practice.
  Shallow cosmetic recesses may be better authored additively; reserve
  booleans for openings or silhouette changes when that matches the design.
  This is modeling/performance guidance, not an algorithmic complexity claim.

### Wrong scale or bounding box

Units mismatch, diameter/radius confusion, wrong extrusion direction or
amount, part not centered as assumed, imported STEP with unexpected units.
Check parameter values, re-measure critical extents, correct the source.

### Missing feature

Wrong add/subtract mode; tool profile not intersecting the target; blind cut
too shallow; a prior operation renumbered the topology the selection relied
on. Confirm the mode, lengthen through-tools, re-select by stable references.

### Selector fragility

Topology changed after a boolean or fillet; similar faces
indistinguishable. Re-select by axis, position, normal, tag, or QL predicate
rather than index.

### Sketch solve failure

Missing or contradictory constraints. Read the solve status and backend code;
fix the constraint set, not the coordinates. Record remaining degrees of
freedom when they are intentional.

### Assembly solve failure
- A nested subassembly constrained through public connectors still owns its
  internal degrees of freedom. If an external dual-fixed relationship cannot
  close, solve the nested mechanism internally first and let the parent
  consume the resulting public interface; do not patch solved placements.

- Constraint unsolved or conflicting → the constraint graph, not the
  geometry.
- Wrong placement → datum or connector frame definition; see
  `assembly-positioning.md` fix order.
- Duplicate component ids, cycles, and invalid placements are rejected — fix
  the structure.

### Reconstruction comparison failure

After a strict comparison fails, group causes with
`BRepComparison.to_error_summary()`: related failures share a root cause,
fix the group together, then run a fresh replay/export/compare cycle.
Repeated non-improvement changes the feature hypothesis instead of tuning
the same parameters again. Stop only per the acceptance hierarchy — and
record the evidence for the stop.

### Export/translation failure

Missing external backend (FreeCAD/FreeCADCmd) → report; offer the neutral
fallback explicitly. Over-coarse tessellation → tighten deflection
parameters and re-export. Missing joints in MJCF → the assembly lacked
explicit constraints; fix the source, never the exported file.

## Diff after repair

When a fix could have affected unrelated geometry, compare before/after —
for reconstruction, a fresh compare cycle; for parts, re-run the full
per-solid gates plus the spec-driven measurements.

## Reporting failed repairs

If a check cannot be repaired in the current environment: what failed, what
was tried, which artifact is still usable, which validation claims cannot be
made, and the next source-level correction to attempt.

## Enumeration is not repair

A loop over candidate sets x parameter values (radii, zoom levels,
`.exactly(n)` guesses tried in sequence) is a symptom that a value is
being guessed that should be derived. Stop enumerating and derive it:
radii from wall thickness or feature size, framing from the bounding
box, cardinality from feature intent. If a value truly cannot be
derived, the check's definition is wrong — narrow it or ask. Swallowing
exceptions inside an enumeration loop (`except: pass`) converts a
search into silent damage.
