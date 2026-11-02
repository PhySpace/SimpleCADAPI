# QL Recipes

**Read when:** you need a worked example of a QL selection: boolean seam curves, root blend, bore rim chamfer, or a sketch datum plane from a face. The model of how selection works, the rules, and what to do when a selection fails are in `ql-playbook.md`; read that first.

Moved from `ql-playbook.md` unchanged. "Ground rule N" means the numbered rules in the playbook; the playbook's "Verified boundaries" lists the engine limits these recipes route around.

## Pattern B — boolean seam curves (D-boss recipe)

A D-shaped boss standing on the long side face of a bar base, unioned with a
1 mm dip into the base and a top that rises 4 mm above the bar: the seam is a
closed 3-D curve set running across the base side face, the base top face and
the bottom imprint. All of it is selectable, then filletable, in two moves.

```python
with scad.GraphSession():
    base = scad.make_box_rsolid(120.0, 30.0, 20.0, (0, 0, 0),
                                top_face_tag="base.top")

    # D boss = box U cylinder; cylinder bottom-face center sits at the
    # midpoint of the boss box's +y bottom edge -> classic D outline
    boss_box = scad.make_box_rsolid(24.0, 10.0, 24.0, (0, 19.0, 0.0))
    boss_cyl = scad.make_cylinder_rsolid(12.0, 24.0, (0, 24.0, 0.0), (0, 0, 1))
    boss = scad.union_rsolid(boss_box, boss_cyl)

    result = scad.union_rsolid(base, boss, clean=False)

    # parents by kernel-proven boolean origin role (arg 0 = body, arg 1 = tool)
    body_sel = ql.faces().where(ql.origin_role("body"))
    tool_sel = ql.faces().where(ql.origin_role("tool"))

    # the seam: edges with one distinct incident face per parent
    seam = ql.edges().incident_to(body_sel, tool_sel, distinct=True).resolve(result)

    # name the seam, then fillet it — the selector feeds fillet directly
    result = scad.apply_tag_rselection(result, seam, "seam.d")
    seam_sel = ql.edges().incident_to(body_sel, tool_sel, distinct=True)
    filleted = scad.fillet_rsolid(result, seam_sel, 2.0)

    # the patches inherit the seam-edge name (verified 7/7 patches)
    ql.faces().where(ql.tag("seam.d")).resolve(filleted)
```

Verified seam inventory for the dimensions above (`clean=False`): 13 edges —
2 vertical lines on the side face (±12, y=15), 5 edges on the base top plane
(the D outline where the boss crosses z=20: 1.0 + 5.367 + 14.056 + 5.367 +
1.0), 6 on the bottom plane (same outline at z=0 plus the 24-long dip
imprint). With `clean=True` the coplanar bottom pieces unify and part of the
imprint seam disappears — keep `clean=False` when the seam itself is the
selection target.

Facts that matter when filleting a seam:

- **`fillet_rsolid` accepts a `ShapeSelector`** for its `edges` argument; no
  need to materialize the list twice.
- A boss/base seam is mostly **concave**: the fillet ADDS volume
  (82780.7 → 82841.1 at r=2). Never assert `v1 < v0` on seam fillets.
- The whole seam filleted at once is a hard kernel case; if a radius fails,
  step down (2.0 → 1.5 → 1.0 verified ladder pattern).

## Recipe: root blend via shared boundary

Edges shared between two named bodies are the first-choice selection
(`discipline/geometric-validation.md`, edge-selection defaults):

```python
walls     = ql.faces().where(ql.prop("geom.type", "==", "CYLINDER"))
plate_top = ql.faces().where(ql.and_(
    ql.prop("geom.normal.z", ">=", 0.999),
    ql.prop("geom.center.z", ">=", 14.5), ql.prop("geom.center.z", "<=", 15.5)))
root = walls.shared_boundary(plate_top, to_kind="edge")

with GraphSession(graph_id="blend") as s:
    blended = scad.fillet_rsolid(solid, root.exactly(card_count), radius=2.0,
                                 generated_faces_tag="fillet.root_patch")
    s.capture_result(value=blended)
```

## Recipe: tagged bore -> rim chamfer

Tag the bore wall right after the cut (Ground rule 3: tag in time),
then chamfer its top rim:

```python
bore_faces = bore.resolve(solid)              # resolve first — see Ground rule 2
tagged = scad.apply_tag_rselection(scope=solid, targets=bore_faces,
                                   tag="role.fastener_bore")
bore_sel = ql.faces().where(ql.tag("role.fastener_bore")).exactly(1)
top_rim = ql.edges().incident_to(bore_sel, distinct=True).where(
    ql.prop("geom.center.z", ">=", 14.0))
rim_card = top_rim.resolve(tagged)
chamfed = scad.chamfer_rsolid(tagged, top_rim.exactly(len(rim_card)),
                              distance=1.0)
```

Gotchas this recipe absorbs:

- `incident_to` on a cylindrical wall returns seam edges too (the
  vertical seam of the cylinder surface sits mid-wall); filter rims by
  an axial coordinate window. The rim card is one closed arc of length
  `2*pi*r`.
- Passing an unresolved selector as `targets` (instead of the resolved
  list) produces a clone foreign to the active session; the next
  operation rejects it with "graph node not owned by active graph".
  Tagging a shape that a later operation has already consumed fails
  the same way — tag immediately after the op that produced the
  faces (Ground rule 3).
- Objects live in one `GraphSession`; passing a solid into operations
  under another session fails loudly. Keep the whole build in one.

## Recipe: selected face -> sketch datum plane

`make_sketch_rsketch(plane=...)` accepts `"XY"/"XZ"/"YZ"` or a plane
mapping — never a Face. Derive the mapping from the selected face:

```python
def plane_mapping_from_face(face):
    c, n = face.get_center(), face.get_normal_at()
    z = (n.x, n.y, n.z)
    ref = (1.0, 0.0, 0.0) if abs(z[2]) >= 0.9 else (0.0, 0.0, 1.0)
    dot = sum(ref[i] * z[i] for i in range(3))
    x = [ref[i] - dot * z[i] for i in range(3)]
    m = sum(v * v for v in x) ** 0.5
    x = [v / m for v in x]
    y = (z[1]*x[2]-z[2]*x[1], z[2]*x[0]-z[0]*x[2], z[0]*x[1]-z[1]*x[0])
    return {"origin": (c.x, c.y, c.z), "x_axis": tuple(x), "y_axis": y}

sketch = scad.make_sketch_rsketch(name="on_face",
                                  plane=plane_mapping_from_face(selected_face))
```

Pick the datum face itself with QL when the intent is structural
("largest up-facing face") rather than positional:

```python
datum = (ql.faces().where(ql.prop("geom.normal.z", ">=", 0.999))
         .order_by(ql.value("geom.area"), desc=True).take(1).exactly(1))
```

`extrude_rsolid(profile=..., ...)` accepts the selected Face directly
as a profile — same object, no re-derivation needed. Extruding the
top face of a 30×20 plate (bore opening r=6 after chamfer) by 2 mm
gives exactly `(30*20 - pi*6**2) * 2` volume.
