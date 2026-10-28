# Discipline: Geometric Validation

Deterministic checks decide pass/fail; scale them to the specification. Every
user-specified dimension requires a targeted measurement.

## Evidence labels

- **SDK contract:** `Solid.get_volume()` returns a volume measurement;
  `simplecadapi.inspect.brep` exposes diagnostic reports such as `valid`,
  volume, and shell closure for BREP outside a `GraphSession`.
- **Validation guidance:** the combination of checks below is a recommended
  gate, not a single SDK `Solid.is_valid()` method.

## Validity is not positive volume

Validity and positive volume answer different questions. Volume is meaningful
per solid, not only after aggregating multiple bodies; a positive and a negative
body can cancel in an aggregate and hide the problem.

After boolean/detail operations, check the gates relevant to the artifact:
`Solid.get_volume() > 0` for positive material volume, plus BREP diagnostics
from `simplecadapi.inspect.brep` (`inspect_shape_rbrepinspection` or
`inspect_step_rbrepinspection`) when validity and shell closure matter. These
inspection functions run outside `GraphSession`; they are diagnostic APIs, not
graph operations. `Solid` has no public `is_valid()` method.

A boolean can also leave a body that is geometrically right but topologically
invalid — correct bounds and volume, one bad face — which survives until the
next operation fails far from the cause. Gate every boolean result, not just
the final one.

## Incremental grounding

Every major step prints a small QL-derived fact: selected face count, a
center, an edge count, volume, bounding box. Print only the facts that
validate the current step — never whole solids or full model objects. This is
what makes drift catchable at the step that caused it instead of at final
review.

## Selection discipline

- Select by tags, axes, normals, positions, or QL predicates — not arbitrary
  topology indexes, which booleans and fillets renumber.
- Plural getters (`get_faces(index)`, `get_edges(index)`, ...) accept ONLY an
  index; enumeration, counting, and measurement go through QL selectors
  (`ql.faces().resolve(shape)`, `len(ql.edges().resolve(shape))`). Indexed
  picks are preserved as graph geo-select nodes.
- `apply_tag(shape=..., tag=...)` attaches a tag to exactly the given shape
  with LOCAL scope — it never propagates downward; `list_tags(shape=...)`
  reads effective tags. Downward/topology-scoped propagation is only exposed
  by `apply_tag_rselection` with an explicit propagation policy. Keep numeric
  facts in metadata, never in tags.
- A QL-selected face or edge reused by a later feature is preserved as a
  stable geo-select node in replayable graphs.

## Selection evidence gate (before fillet/chamfer)

A detail operation succeeding proves the kernel built a solid — not
that the right edges were selected. Filleting 26 unrelated edges
returns a valid solid. Before every `fillet_rsolid`/`chamfer_rsolid`:

1. Print the selection card: count, and for each edge its length and
   center (faces: center and area). Read it — a seam edge or a neighbor
   feature inside the window shows up here as an unexpected hit.
2. Assert the cardinality you designed for (`.exactly(n)`), where n
   comes from feature intent, never from adjusting n until the call
   succeeds.
3. When the selection carries tags, render it once with
   `render_screenshot_rpath(..., highlight_tags=[...])` and state the
   view used. Seeing the selected edges is the check.

Anti-patterns, each a documented silent-wrong-part delivery:
- Bare enumeration of topology with Python loops or post-filtered lists —
  the no-argument getter list form is removed; every read goes through QL,
  and picks use `get_edges(index)` only for edges you can name and intend.
  Booleans and fillets renumber topology; a predicate survives, an index
  guess does not.
- Enumerating candidate edge sets x radii with `except: pass`; a hit
  confirms the selection is uncontrolled, it does not solve it.
- Counting generated `face.*` tag faces as proof the blend landed on
  the intended edges — tag-face count proves the operation ran, not
  where.

Choose evidence for what it can refute, not for how easily it passes.
An operation returning a solid refutes nothing about which edges were
picked; tag-face counts prove that an operation ran, not where it
landed. The discriminating check shows the selected geometry (a
highlight render) or measures the claimed property directly (the swept
envelope along the insertion path).

## Edge-selection defaults

In order of preference:

1. Blend between two named bodies -> intersection semantics:
   `ql.shared_boundary(body_a, body_b, to_kind="edge")` — the real
   shared boundary, not a geometric window approximating it.
2. Role surface -> tag predicate on the `role.*` tag attached when the
   feature was created.
3. Geometric window (last resort) -> bounded predicate on
   normal/center/length, printing every hit's center and length before
   use (this is the selection card).

Index getters are for intentional picks you can name in this step —
never for discovering which edges to blend.

Predicate vocabulary, lineage routes, copy-paste recipes, and
shared-boundary failure signatures (tangency, overhang): `ql-playbook.md`
in the skill references root.

## Replay as a gate

When a flow claims replayability, prove it: `export_model_json(session=...)`
→ `replay_model_json(json_str=...)` in a fresh process, and check the
replayed output count/values. A replay that was never run is a claim, not a
check.

## Define what the check proves before writing it

1. Posture or path? A fit/assembly claim for a fastened feature is
   proven by sweeping the fastener envelope along the insertion path
   (slide-in, rotate-in), not by intersecting the final posture.
   Final-posture clearance passing is not evidence of assemblability.
2. Verification geometry vs design geometry: if the check body also
   cuts, or a cut was removed to make the check pass, state which role
   it plays. A verification envelope that cannot coexist with the
   design validates neither. When the envelope must also machine the
   clearance, it is a design feature — treat it as one.
3. A failed check closes by changing the design, or by changing the
   check's definition with the user — never by weakening the check or
   deleting the interfering material out of the verification body.
4. Convert review feedback into a predicate before implementing it:
   "it occludes the hole in the render" -> does measured material
   intersect the hole cylinder? Run the cheap experiment that
   distinguishes occlusion from intrusion before modeling either.

## Spec-driven measurement

Every dimension, clearance, offset, and relationship in the brief gets a
targeted check:

- Distances and thicknesses: bounded measurements on selected geometry.
- Flush/centered interfaces: measured deltas, not visual impression.
- Patterns: at least two units measured for spacing/angle before trusting the
  pattern.
- Assemblies: solve residuals, coaxiality of mated axes, flush faces, repeated
  occurrences at named positions (`assembly-positioning.md`).

## OCCT measurements on an SDK shape

When the checks need more than the SDK exposes (point-in-solid, minimum distance between shapes, Boolean overlap
volume, centroids and inertia), write them with OCP exactly as OCCT references and CadQuery do. With OCP installed (the
`verify` extra), `shape.wrapped` **is an OCP shape** of the class of its kind (`TopoDS_Solid`, `TopoDS_Face`,
`TopoDS_Edge`, ...), so this runs as written:

```python
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

props = GProp_GProps()
BRepGProp.VolumeProperties_s(solid.wrapped, props)
volume = props.Mass()
```

`wrapped` is a copy made through OpenCASCADE's binary format (milliseconds for a part); changing it does not change the
SDK shape, and a shape you build in OCP comes back into the SDK with `simplecadapi._glue.bridge.from_occt`. Without OCP
installed `wrapped` is the SDK's own OCCT shape, which OCP functions reject: install the extra for verifier scripts.
`SCA_WRAPPED=native` or `SCA_WRAPPED=ocp` forces one view.

## Visual review converts to deterministic checks

A visual concern found at review (misplaced feature, wrong silhouette) is not
closed by "looks better now": convert it into a deterministic geometry check
that would have caught it, then run that check. Rendering and comparison
renders (`render_step_comparison_rpath`) are evidence for review — visual
similarity never replaces strict comparison where the contract requires it.

## Report only what ran

State the checks that actually executed, with their outcomes. An intended
check that was not run is reported as not run — implying success without
running a check is the cardinal reporting failure. Structural safety, fatigue,
thermal, vibration, tolerance compliance, and regulatory fitness are never
claimed from geometry alone (`manufacturing-boundaries.md`).
