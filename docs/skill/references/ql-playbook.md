# QL Selection Playbook

Copy-paste patterns for selecting **what an operation produced** with QL —
side faces and rims of extrude-like features, output slots of primitives,
intersection curves (seams) of booleans, bore rims and root blends — and the
operations that consume those selections (fillet, chamfer, sketch datums,
extrude profiles).

Every pattern in the Ground rules and Patterns A/B was executed and checked
against `dev` @ `e87df6b` (2026-09-02, 33/33 checks across four harnesses:
extrude family, primitives, sweep/loft, D-boss seam). Snippets are trimmed
copies of the passing harness code. The recipes (selection loop, predicate
vocabulary, root blend, bore→rim chamfer, face→datum plane, facts printing)
were executed against `dev` @ `0ec8b76` (2026-09-06, 11/11 checks — see
Verification harnesses). Anything listed under "Verified boundaries" is a
real, current engine limitation — do not work around it silently; route
around it as shown.

## Ground rules

1. **Model inside `scad.GraphSession`.** Topology tracking, role tags, and
   name projection only exist on session paths. Legacy (session-less) calls
   attach whole-solid tags at most: no per-face roles, no projection, no
   `origin_role`/`output_role` evidence.

2. **Tag subshapes through the scope that will consume them.** Bindings live
   in a shape's own entity cache:

   ```python
   profile = scad.apply_tag_rselection(profile, [edge], "profile.long.a")
   ```

   Tagging an edge resolved from the *wire* under a face is invisible to the
   face (different cache). `apply_tag_rselection` returns a clone — always
   reassign the returned view. Pass `targets` as a **resolved list**; an
   unresolved selector as `targets` yields a clone foreign to the active
   session, and the next operation rejects it with "graph node not owned by
   active graph" (same surface message as the timing defect in rule 3).

3. **Tag the value you go on with.** A tag reaches the results of the
   operations that consume the tagged value (the clone
   `apply_tag_rselection` returns), through their recorded history. A tag
   applied to a shape an operation has already consumed can never reach
   that operation's result. Tagging such a stale value is rejected with
   "graph node not owned by active graph" — the message names ownership,
   but the real defect is timing. When targets only become addressable
   later, re-derive the selectors from the newest result and tag that
   (Pattern B tags the seam directly after the union; the bore recipe
   below tags right after the cut).

4. **Enumerate with QL, not plural getters.** `ql.edges().resolve(shape)`,
   never bare `get_edges()` (raises by design; enumeration is QL-exclusive).

5. **Tags are a view over recorded history.** Every tag assignment
   (`apply_tag_rselection`, an op-kwarg tag such as `top_face_tag=`) is a
   graph node; `ql.tag(...)` on a later shape finds the entities the tagged
   ones became, through each operation's kernel history, as the tag's
   lineage policy allows (default `continuation_fragment`: a face cut in two
   keeps the tag on both pieces). Verified per family in
   `test/test_element_ref_history.py` (audit):

   | Channel | Example | Survives boolean | Survives fillet/chamfer, shell, copies, patterns, transform/scale/offset/draft |
   | --- | --- | --- | --- |
   | op-kwarg role naming | `extrude_rsolid(..., end_face_tag="cap.top")`, `make_box_rsolid(..., top_face_tag="base.top")` | yes | yes |
   | plain user tag on a face | `apply_tag_rselection(solid, [face], "base.body")` | yes | yes |
   | source-edge naming | `apply_tag_rselection(profile, [edge], "profile.long.a")` → side face; `apply_tag_rselection(result, [seam], "seam.d")` → fillet patch | yes | yes (the op names the generated face after its edge) |
   | `origin_role("body"/"tool")` | parent argument of a boolean | single-step only | no |
   | `output_role("<slot>")` | `extrusion.end`, `box.top`, `fillet.patch` | single-step only | own op only |

   "Single-step" means the metadata describes the last operation that touched
   the shape; the next tracked operation overwrites it. A tag ends where the
   history says the entity ends: a face a cut removes, a face a feature
   replaces by a generated one (a fillet's patch is a new face, not the
   edge), or an operation that records no history. `scad.explain_tag(face,
   tag)` shows the binding and the lineage that carried it. The `lineage`
   scope is the carried part alone; `effective` (the default) includes it.

## The selection loop (card before cardinality)

Never hand a selector to an operation unresolved. Resolve it first,
print the card, read it, then assert:

```python
sel = ql.edges().shared_boundary(walls, top, to_kind="edge")
card = sel.resolve(solid)                     # probe without cardinality
for e in card:
    c = e.get_center()
    print(f"len={e.get_length():.3f} center=({c.x:.1f},{c.y:.1f},{c.z:.1f})")
sel = sel.exactly(len(card))                  # now freeze the count
```

Read the card against the geometry you imagined: expected count,
expected lengths (a full circle at radius r prints `2*pi*r`; a half
circle prints half that). A mismatch is a finding about the part, not
about QL. `.exactly(n)` failing loudly (`expected exactly 2 edge(s),
got 0`) is the gate working — widen or fix the window, never lower n
until the call succeeds.

## Predicate vocabulary

| Family | Examples | Notes |
| --- | --- | --- |
| Geometry | `ql.prop("geom.type", "==", "CYLINDER")`, `geom.center.x/y/z`, `geom.normal.x/y/z`, `geom.area`, `geom.length` | types are uppercase enums (`PLANE`, `CYLINDER`, ...) |
| Naming | `ql.tag("role.fastener_bore")`, wildcards `ql.tag("fillet.*")` | tags attached via `apply_tag_rselection(scope, targets=<resolved list>, tag=...)` |
| Lineage | `ql.output_role("fillet.patch")`, `ql.op("fillet")`, `ql.origin_role("contour_edge")` | see "Lineage routes" below |
| Boolean | `ql.and_(...)`, `ql.or_(...)`, `ql.not_(...)` | combine into one `.where(...)` |

**Coordinates take ranges, never equality.** Measured centers carry
float noise (`center.z` reads `15.000000000000002`); an `==` window
silently misses. Use paired bounds:
`ql.prop("geom.center.z", ">=", 14.5)` together with
`ql.prop("geom.center.z", "<=", 15.5)`.

**One property is never enough after a boolean or blend.** After a
fillet, the patch faces are cylinders too — `geom.type == "CYLINDER"`
matched five faces on a plate with one bore and four corner blends.
Discriminate by axis window plus size:

```python
bore = ql.faces().where(ql.and_(
    ql.prop("geom.type", "==", "CYLINDER"),
    ql.prop("geom.center.x", ">=", 14.9), ql.prop("geom.center.x", "<=", 15.1),
    ql.prop("geom.center.y", ">=", 9.9),  ql.prop("geom.center.y", "<=", 10.1),
    ql.prop("geom.area", ">=", 200.0),
)).exactly(1)
```

## Pattern A — extrude-like outputs

The five canonical moves, on `extrude_rsolid` (identical selectors work for
`sweep_rsolid` / `loft_rsolid` and for primitives, which are the kernel-native
extrudes):

```python
with scad.GraphSession():
    wire = scad.make_rectangle_rwire(30.0, 10.0, (0, 0, 0), (0, 0, 1))
    profile = scad.make_face_from_wire_rface(wire)

    # 1) name profile edges through the profile scope (classifying by length
    #    and center sign stays the most robust addressing)
    for ent in ql.edges().resolve(profile):
        if abs(ent.get_length() - 30.0) < 1e-6 and ent.get_center().x > 0:
            profile = scad.apply_tag_rselection(profile, [ent], "profile.long.a")
        elif abs(ent.get_length() - 10.0) < 1e-6 and ent.get_center().y > 0:
            profile = scad.apply_tag_rselection(profile, [ent], "profile.short.a")

    solid = scad.extrude_rsolid(
        profile, (0, 0, 1), 8.0,
        start_face_tag="cap.bottom", end_face_tag="cap.top",
        side_faces_tag="wall.side",
    )

    # 1. side face by inherited profile-edge name (also: wall.side group = 4)
    ql.faces().where(ql.tag("profile.long.a")).resolve(solid)

    # 2. vertical corner edge shared by two side faces
    side_long = ql.faces().where(ql.tag("profile.long.a")).exactly(1)
    side_short = ql.faces().where(ql.tag("profile.short.a")).exactly(1)
    side_long.shared_boundary(side_short, "edge").resolve(solid)

    # 3. edge shared by the end face and one side face
    cap = ql.faces().where(ql.tag("cap.top")).exactly(1)
    cap.shared_boundary(side_long, "edge").resolve(solid)

    # 4. end face (kernel-role channel; kwarg name gives the same face)
    ql.faces().where(ql.output_role("extrusion.end")).resolve(solid)

    # 5. the end-face rim
    cap.boundary("edge").resolve(solid)
```

Verified extensions:

- **Primitives** carry the same slots natively: `box.top/bottom/front/back/
  left/right`, `cylinder.start/end/side/start_boundary/end_boundary/seam`,
  `cone.start/end/side/start_boundary/end_boundary/seam`. Query with
  `output_role(...)` or the matching `*_face_tag` / `*_edge_tag` kwarg.
  Box orientation for `width=x, height=y, depth=z`: front/back = ±x,
  left/right = ±y, top/bottom = ±z.
- **Planar profiles share the box axis convention**: for a +z normal,
  `width` spans global x (`make_rectangle_rwire(30, 10)` spans 30 in x and
  10 in y; identical on session and legacy paths). The in-plane basis is the
  reference vector projected onto the plane, so a +z-normal profile frame is
  exactly the global (x, y, z).
- **Seam edges without any name** — select by topology signature (the seam is
  the only full-height edge with a single incident face):

  ```python
  ql.edges().incident_face_count(exactly=1).resolve(solid)
  ```

- **sweep**: profile-edge names reach the swept side face exactly as with
  extrude (verified: circle edge name → cylindrical wall). `sweep.start/end`
  name the caps; cap rim and cap∩side shared edge select identically.
- **loft**: `loft.start/end` caps and the `side_faces_tag` group work; per-side
  identity is NOT stable (section correspondence is kernel-matched), so select
  sides as a group or post-hoc — never index them.

## Recipes (worked examples)

Pattern B (boolean seam curves, the D-boss recipe, with seam inventory and fillet facts), the root blend recipe, tagged bore -> rim chamfer, and selected face -> sketch datum plane are in `ql-recipes.md`. The rules above and the failure signatures below apply to all of them.

### Shared-boundary failure signatures (read them, do not fight them)

A shared boundary resolves against the real topology; when it does not
match the shape you imagined, the difference is diagnostic:

| Card looks like | Cause | Fillet result |
| --- | --- | --- |
| One closed arc, length `2*pi*r` | feature seated with clearance (axis-to-wall distance > radius) | succeeds |
| Two arcs meeting at one point, lengths summing to `2*pi*r` | **tangency**: axis-to-wall distance exactly equals the radius; outline touches the wall in one point | kernel crash `TopOpeBRepDS_DataStructure::Point` at any radius |
| Half arc / extra short arcs | feature overhangs the wall (axis outside or on the wall) | kernel build aborts |

Reason from these the same way for every shared-boundary case: compare
the card's segment count and lengths with the intersection curve you
imagined; look for the singular point where segments meet; treat
"selection resolved fine but every radius crashes" as evidence of a
degenerate configuration in the design, not a selector bug. Before
blending a seated feature, assert clearance: axis-to-neighboring-wall
distance must exceed the blend radius (same family as fastener
envelopes, `discipline/mechanical-modeling.md`).

## Lineage routes (proving what an operation produced)

| Question | Route | Verified semantics |
| --- | --- | --- |
| Which faces did this operation generate? | `generated_faces_tag="name"` param, then `ql.tag("name")` | kernel-proven patch faces only |
| Same, without pre-declaring a tag | `ql.output_role("fillet.patch")` | faces whose track metadata carries `result_roles` and `events=["generated"]` |
| Everything the operation touched (new + modified)? | `ql.op("fillet")` | superset: includes faces with `events=["modified"]` |

Counting patch faces after a blend is the proof that the blend landed
where intended — pair it with the highlight render from the selection
evidence gate. Track metadata is authoritative: a generated face
carries `events: ["generated"]`, a reshaped survivor carries
`["modified"]`.

## Facts printing

For ad-hoc facts outside selectors, the list query mirrors the selector
API:

```python
ql.select(ql.faces().resolve(shape)).where(ql.prop("geom.type", "==", "PLANE")) \
  .order_by(ql.value("geom.area"), desc=True).limit(3).all()
```

## Verified boundaries

What the harnesses established about the engine's reach — limits and
behaviours to design around:

1. **Tags stop where kernel history stops.** An operation that records no
   topology history ends every tag through it (none of the solid modelling
   operations do since the stable-refs work; check `node.topo_delta` for a
   new operator). Within history a tag follows only entities that live on:
   a generated face is named after its source by the operation itself
   (fillet patches, extrude sides), never by continuation.
2. **Tags assigned outside a `GraphSession`, imported sidecar facts and
   sketch topology names live on the shapes** and are carried by the
   operations' projection, not by the recorded view: model inside a session
   so the graph carries your tags (and they survive the cell cache).
3. **`origin_role` / `output_role` are single-step metadata.** After the seam
   fillet, every face reports the fillet's own roles; the boolean body/tool
   partition is gone. Query parent identity immediately after the boolean, or
   carry it as a name.
4. **Primitive auto role tags (`face.box.top`, ...) are tags like any other:**
   they follow their face through later operations in the effective scope,
   so `face.box.top` on a finished part means "descends from the box's top".
   Use `ql.output_role(...)` when you mean "the role in the last operation".
5. **The planar profile in-plane basis switches discontinuously near
   vertical.** The reference-axis branch (`|z_z| > 0.9`) in the plane-basis
   helper swaps its reference between global X and Z, so sweeping a plane
   normal across roughly 25° from vertical rotates the in-plane frame
   abruptly. When normals vary, address profile edges by length and center
   sign rather than by axis assumptions.
6. **An N-ary cut is followed step by step:** its steps name the
   intermediate solids, and the recorded delta composes them back to the
   real inputs, so names and references cross the whole chain
   (`test_an_n_ary_cut_composes_its_steps`).

## Verification harnesses

| Harness | Checks | Result |
| --- | --- | --- |
| extrude family (5 capabilities + group naming + geometry identity) — 2026-09-02, dev @ `e87df6b` | 8 | PASS |
| plane-axes convention (frame properties, rectangle extents on both paths) — 2026-09-02, dev @ `e87df6b` | 5 | PASS |
| primitives (box slots, rim, shared edge, kwarg naming, cylinder seam/rim/topology signature) — 2026-09-02, dev @ `e87df6b` | 8 | PASS |
| sweep + loft (profile-edge inheritance, caps, rims, shared edges, seam-by-topology) — 2026-09-02, dev @ `e87df6b` | 9 | PASS |
| D-boss seam (origin-role partition, 13-edge seam inventory, dual-parent witnesses, fillet, 7/7 patch naming) — 2026-09-02, dev @ `e87df6b` | 8 | PASS |
| recipes (loop card, predicate windows, bore→rim chamfer with resolved targets, root blend + lineage routes on a chamfered plate, face→datum plane mapping + face-profile extrude, facts printing) — 2026-09-06, dev @ `0ec8b76` | 11 | PASS |
