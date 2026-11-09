# Editor GUI features: what the buttons write, and the same operations from the command line

**Read when:** a person made features with the editor's buttons (cells with a `# gui:` line, `scad.ref` selections,
workplanes, sketches made in the canvas), or you drive the same operations yourself with `sca feature` / `sca sketch`.
The collaboration rules (who edits what, `sca cell`, selections, parameters) are in `editor-collaboration.md`.

## Features the person made with buttons

The editor also has a Features tab and an operation palette (box, cylinder, extrude, hole, fillet, patterns ...). A click
writes two ordinary cells, so you read and edit them like any other:

```python
# ---- params: hole ----
HOLE_DIAMETER = scad.var(name="hole_diameter", default=6.0, unit="mm", comment="Diameter")  # ui: slider(...)

# ---- feature: hole (subtract) ----
# gui: {"spec":"hole","v":1,"values":{...}}
...one operation that makes the new name `hole`...
```

- The `# gui:` line is how the form is rebuilt. A cell without it is code and the form never rewrites it. To take a
  GUI feature over as code, delete the `# gui:` line (or ask the person to); to change a number, edit the `# params:` cell
  or the form, not the call.
- GUI commands carry the code they were made from: if you edited the cell in between, the command is refused (409), it
  does not overwrite you. The same holds for the person's undo of a GUI command.
- Selections in a GUI cell are stable references, one statement per selection slot, written from the person's picks
  (the editor names each picked entity in the kernel with `scad.ref.of`):

  ```python
  _edges = scad.ref.edges(scad.ref.edge('base', 'make_box_rsolid', between=('box.front', 'box.top'), guard=('LINE', (20, 0, 20), 30)))
  round = scad.fillet_rsolid(solid=base, edges=_edges, radius=ROUND_RADIUS)
  ```

  Read them as data (feature, operation, role; see `ql-playbook.md` rule 6). They survive booleans, blends and edits of
  the referenced feature. When one no longer names exactly one entity the feature fails with `ElementRefError` and the
  Features tab shows it amber (split: the pieces) or red (lost: where, why, the look-alikes); the person's click writes
  the choice into the literal (`piece=1`, or a new reference). Never replace a failing reference by a geometric window
  or "fix" it by guessing a piece: ask the person; the editor's `ref_status` / `ref_repair` commands (the
  editor API, `POST /api/features {"op": "ref_status", "cell": ...}`) report and write them. You may write such a statement yourself; keep it one
  `scad.ref.<faces|edges>(...)` call so the form still reads it. An older cell with a tag-or-geometry recipe block
  (`_x_by_tag`, `_x_by_geometry`) still runs and its form keeps the block; a pick the kernel cannot name (a body
  without recorded history, `sca feature add` with geometry only) is still written that way.
- A new part notebook (`sca new NAME`, or the editor's "new") has no cells and a `kind = "part"` header: no product cell is written,
  the runtime makes the Part from the open bodies (see `docs/guides/notebook-runtime.md`; a solid made with "New body"
  is one more body of the same Part, not an assembly), so every new feature previews
  and a deleted cell cannot leave the notebook without a product. Setting connectors (or "use as product" on a body
  that is not the last) writes an explicit `make_part_rpart` cell, which then wins.
- Besides the curated features (box, hole, pull face, extrude of a sketch ...), every SDK and standard-library operation
  the forms can offer is a feature of its own, `op.<operation>` (`# gui: {"spec": "op.make_spur_gear_rsolid", ...}`): the
  form is made from the operation's signature (`sca ops NAME`), and the cell is one plain call
  (`gear = scad.std.gear.make_spur_gear_rsolid(n_teeth=GEAR_N_TEETH, ...)`) with its numbers in the params cell.
  `sca feature add op.<operation> --values '{...}'` does the same from the command line.
- Colours and names are SDK operations too, so the forms offer them: `op.set_body_appearance_rpart` (a colour picker,
  an opacity slider in [0, 1], a body name; the viewer draws each body in its colour) and `op.apply_tag_rselection`
  ("name a face": pick the faces, type the tag). A colour slot is the `color` kind of the catalog
  (`simplecadapi.types.Color`); the picker's `#rrggbb` is written as linear RGB. A person's face name is a tag: read it
  with `scad.ql.tag(...)`, never invent another naming scheme.
- Placing a workplane by hand: Space with nothing selected (or one flat face; the command "Workplane") shows a draft plane
  with move arrows and turn rings on its base (the picked face, else the active workplane, else XY; the panel lists XY,
  XZ, YZ and every workplane). Drag (1 mm / 5 degree steps, Shift for free) or type the six numbers; G move, R turn,
  Enter creates, Esc cancels. The cell is `wp = scad.make_workplane_offset_rworkplane(<base>, offset=(...), rx=..., ry=...,
  rz=...)` (on a face: `make_workplane_from_face_rworkplane(face, x_dir=...)` as the base), the numbers in its params cell.
  Each new plane becomes the active one and the next Space starts on it: a chain of planes in space, each sketched on and
  promoted to a wire (below) to loft or sweep between. Shift+Space looks straight at the active workplane.
- 3D curves (W, or the command "3D curve"): lines (L), three-point arcs (A) and splines (S) one after another through points
  on the drawing plane (the active workplane, else XY; Tab changes it between points), snapped to the model's vertices
  and edge midpoints, the workplanes' origins, the ends of other curves and the plane's grid. Enter makes one `curve`
  feature per line, arc or spline (`path`, `path_2` ...; `# ---- feature: path (datum) ----`), each an **edge**: a point
  drawn on a workplane is `wp.point(u, v)` (it follows the workplane), one snapped to a vertex is
  `scad.ref.vertex(...).one(base).get_coordinates()` (it follows the model), one at an end of another curve (the next
  curve of the path, or a snapped end) is `path.get_end_vertex().get_coordinates()` (it follows that curve), others are
  numbers. A wire is made where one is needed, from the curves picked (`make_wire_from_edges_rwire([path, path_2])`); an
  older curve cell of several segments is still one wire. The kernel reports every top-level value's kind, so a curve
  or face written as code is a value, not a body. Every wire or edge value is drawn in the viewport from the kernel's
  samples (`runtime/live_curves.py`) and picked with the "sketch / curve / surface" selection mode.
- Surfaces from curves (pick curves in that mode): Sweep (one curve: `op.sweep_rsolid`, a sketch picked with it is the
  profile), Ruled surface (two: `op.make_ruled_surface_rface`), Loft surface (`op.loft_rshell`, in the order picked),
  Fill (a closed loop: the `fill` feature, `make_surface_patch_rface` of `SurfaceBoundary`s), Flat face (a flat loop:
  `flat_face`, `make_face_from_wire_rface` with the loop's normal), Network surface (two families of crossing curves,
  found from where they cross: `op.make_gordon_surface_rface`), Join into a wire (the `wire` feature). The face and
  shell values no later cell reads are drawn with the model (`node/surface/<name>`, light blue, both sides) and picked
  whole in the same mode: Sew (the `sew` feature: `sew_faces_rshell` of faces and shells) and Close into a solid
  (`solid_from_shell`: `make_solid_from_shell_rsolid`, which becomes the part's body).
- Connectors of the part are placed like workplanes: pick one flat face, then "Connector" (selection bar, command bar,
  or the assembly tab's "on picked face"): a frame with move arrows and turn rings sits on the face; name it and Add.
  It is written into the product cell (`add_connector_rpart(...)`, `# gui-connectors:`); the assembly tab lists, edits
  and deletes the part's connectors.
- A hole is placed with the pointer: while its form is open a ghost of the hole (its diameter and depth) follows the model
  under the pointer, along the surface's normal there by default ("along the picked face's normal"), and a click writes
  the start point and direction into the form. Nothing is computed by the kernel until Add.
- Pick intents have keys: 1 vertex, 2 edge, 3 face, 4 solid, 5 component, 6 sketch. Sketches are drawn only while sketches
  are what a click picks (or one is picked, edited, or a form takes a sketch profile).
- There are no shape-specific shortcuts ("extrude a rectangle", "loft two circles"): a profile is a sketch, and loft, sweep
  and the rest are the SDK operations themselves (`op.loft_rsolid`, `op.sweep_rsolid` ...). Operations that differ only in
  what they make are labelled with it ("Loft → solid", "Loft → surface"). Older cells written by those shortcuts still run;
  the editor shows them as code features.
- Workplanes from picks: with any other selection, Space (or the command "Workplane from selection") writes a `workplane` feature
  (`# ---- feature: wp (datum) ----`, `wp = scad.make_workplane_*_rworkplane(...)` with the picks resolved inline, offset
  and flip in the params cell). (The command alone on one flat face -> on it.) A face and an edge -> x along the edge; two parallel faces ->
  the midplane; three vertices (in pick order) -> through them; one edge -> through it, turned by an angle. The new
  workplane becomes the active one (the camera turns to it, it is drawn blue); a new sketch goes on it, and the plane
  chooser lists every workplane variable. Each workplane variable of the notebook (GUI or code) is drawn as a small
  labelled patch at the frame the kernel computed (the server's `workplanes` envelope).
- A sketch on a workplane has `plane={"workplane": "wp", origin, x_axis, y_axis}` in its `# gui:` document and
  `plane=wp` in its code: the frame in the document is only for drawing before the cell runs; the cell follows `wp`.
  A workplane cell reads the body without consuming it (the body stays the open body / product).
- A split tag is shown, not hidden: when an operation splits a tagged entity (its pieces carry `<tag>.split1` ..), the
  viewport highlights each piece in its own colour and a notice names the tag, the operation and the pieces' tags
  (hide the highlight or dismiss it there). `sca snapshot` lists the same as `tag_splits`. Read it as a question:
  was the split meant? If later code needs a piece, tag it after the split.
- Unattended: the buttons are not available; write the cells yourself (see `discipline/notebook-cell-design.md`).

## The same operations from the command line

An agent does not click: `sca feature` and `sca sketch` do what the buttons do, with the same checks, as JSON in and JSON out.

```bash
sca feature specs [SPEC]             # operations and their typed slots (lengths mm, angles deg, bodies by name)
sca feature ls                       # features, bodies, tip, product, defaults
sca feature add box --name base --values '{"width": 40, "height": 30, "depth": 20}'
sca feature add fillet --values '{"radius": 2}' --selections '{"edges": [{"kind": "edge", "entity_id": "entity/..."}]}'  # named by the kernel; geometry-only items keep the older recipe
sca feature edit base --values '{"width": 50}'      # a GUI feature; a code feature is refused
sca feature edit cup --selections '{"faces": [{"kind": "face", "ref": {...}}, {"kind": "face", "entity_id": "entity/..."}]}'  # keep a held reference (`sca feature ls`: gui.refs), add a pick
sca feature rm base | sca feature undo | sca feature redo
sca sketch ls | get CELL | put CELL -f doc.json | solve CELL
sca sketch op CELL trim --args '{"entity": "h", "at": [8, 0]}' [--dry-run]
sca sketch op CELL extend --args '{"entity": "h", "end": "end"}'
sca sketch op CELL insert_spline_anchor --args '{"spline": "s1", "at": [12, 8]}'   # also remove_spline_anchor, convert_spline_to_anchors
```

- The edits are the SDK's own operations, not editor features: `sca sketch op CELL trim ...` calls `scad.trim_rsketch` on the
  sketch the document builds and writes the result back, so the same edit in a notebook cell is
  `_sketch = scad.trim_rsketch(sketch=_sketch, entity="h", at=(8.0, 0.0))`; `scad.diff_sketch_rsketchdiff(before=..., after=...)`
  says what changed (`created`, `removed`, `changed` entities and `created_constraints`, `removed_constraints`,
  `changed_constraints`). `trim` cuts an entity at the crossings around the point `at` on the solved geometry and ties each cut
  point to the entity that made it (`point_on`); a piece keeps the horizontal/vertical constraint of its line; dimensions that
  no longer hold are removed (they appear in `removed_constraints`). New ids are the lowest free `p<n>`, `l<n>`, `a<n>`, `s<n>`
  and `c_<kind>_<n>`. `--dry-run` prints without writing.
- A sketch document holds lines, circles, arcs and B-splines. A B-spline entity is
  `{"id": "s1", "kind": "bspline", "start": "p1", "end": "p4", "control_points": ["p1", "p2", "p3", "p4"], "degree": 3}`
  (control points are point ids, the first and last are its start and end; a closed one starts and ends on the same point);
  it becomes `scad.add_bspline_rsketch(..., control_points=[...], degree=3)`. `solve` returns each solved B-spline as the SDK
  samples it (`curves`: points, normals, curvatures; the editor draws the curve and its curvature comb from them), and the
  crossings trim would cut at (`crossings`, B-splines included). trim cuts B-splines (and lines/arcs/circles at B-splines),
  extend lengthens a B-spline or a line onto one; a trimmed or extended B-spline has non-uniform knots, so its document entity
  also carries `"knots"` (distinct, increasing) and `"multiplicities"` (they add up to control points + degree + 1).
- The spline tool (B) is a pen: a click places an anchor, press-and-drag pulls out its two handles; the curve is a B-spline in
  anchor form (`"knots": [0, 1, ..], "multiplicities": [4, 3, .., 4]`, control points `[A0, out0, in1, A1, ..]`; see
  `sketch-and-features.md`, "B-splines with anchors"). Picking the spline shows its handles: dragging an anchor carries its
  handles; dragging a handle moves only that handle (each side has its own direction and pull; Shift while dragging turns
  the other handle into line, keeping its length; S smooths the picked anchors). Inserting anchors is part of drawing: a
  point, line or pen click on an anchor-form spline's curve (the cursor shows "+ anchor") inserts an anchor there with
  `insert_spline_anchor_rsketch` and uses that point. With a spline picked, Shift+A (or the "anchors" toolbar button) is
  anchor mode: a click on a curve adds an anchor, a click on an inner anchor removes it (`remove_spline_anchor_rsketch`);
  Esc or Shift+A leaves. Delete removes the picked anchor; a double-click on the curve inserts one. A B-spline with control
  points (older documents) shows its control polygon and a "convert to anchors" button (K).
- A sketch document may say `"output": "wire"`: the cell then ends in
  `name = scad.make_wire_from_sketch_rwire(sketch=_sketch, profile=<i>, ...)` (a closed loop or an open chain from
  `inspect_sketch_rsketchprofiles`, whose `closed` says which) and the notebook lists it as a wire, so `op.sweep_rsolid`
  (path) and `op.loft_rsolid` (sections) take it; face sketches stay the profiles extrude/revolve/cut take. The editor's
  sketch bar has the face / wire switch and the profile list.
- Errors name ids (`there is no entity 'x'`, `nothing is ahead of the end of h`); fix the call, do not retry it unchanged.
- Everything a command writes is an ordinary cell; `sca cell` still works on it (see the `# gui:` rules above).
