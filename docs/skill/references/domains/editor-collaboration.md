# Editor collaboration: working with a person in `sca edit`

**Read when:** a person has the code-first editor open (`sca edit`) and you edit the same notebooks (a selection, a cell reference or a tuned value arrives).

Use this domain when a person has the code-first editor open (`sca edit`) and
you work on the same notebooks: they click, drag and tune; you read files and
edit code. It is not a workflow. The modeling you do still follows the workflow
you selected; this page says how to see what the person sees and how to hand
work back.

**Unattended:** there is no person and no editor. Do not start `sca edit`; edit the notebook file directly, check it with
`sca run <notebook>` and read its report instead of the snapshot, the viewport image or a selection cell. A selection
you were handed in the task is resolved and checked like any selector. Never wait for a person to run, pick or tune
anything (`discipline/operating-modes.md`).

The notebook file is the shared state. The editor autosaves every edit to
it, and every message the person gives you (a selection, a cell reference, a
tuned value) is also something you can read from disk. Never rely on what the
person says they selected when the file or the snapshot can tell you.

The editor holds the open notebook in memory and is the one writer of its
file. While it runs, **`sca cell` is the only way to change a regular cell**:
writing the file behind the editor's back races its next save, and the page's
version or yours is lost. Edit the file directly only when no editor is
running (then nothing else holds it), or for the cells `sca cell` refuses
(the setup cell and `@app.function` cells): the editor takes those file
changes in.

1. **`sca cell` (always, for regular cells).** It edits through the editor: the page shows the
   change live (no reload, no flicker), the cell runs, and you get its state back.
2. **Edit the file** — only with no editor running, or for a setup / `@app.function` cell. The
   editor notices a saved change within a second, compares
   it with its cells and applies only what differs (changed cells are edited in
   place and run again, added or removed cells appear or go away). A change to the
   setup cell or an `@app.function` cell restarts the kernel instead. A file that
   does not parse is ignored until the next save that does.

If the person has the same cell open with unsaved typing, **your version wins**:
their text is dropped and kept in the editor's log for them. Do not rewrite a
cell the person is typing in without telling them.

## Start the editor for a person

```bash
sca edit <workspace>          # a directory of notebooks, or one notebook
sca edit <workspace> --no-browser --port 7180
```

- Needs the `editor` extra (`pip install "simplecadapi[editor]"`); without it
  the command says so and stops.
- The workspace is any directory tree, scanned to any depth. Models are the
  notebooks whose header has `[tool.simplecadapi]`; assemblies list the parts
  they `use(...)`. Open the assembly to see the product, a part to edit that
  part. Working in a subfolder is fine; what hides a file from the workspace
  tab is its name: directories and files starting with `.` or `_`, and
  anything under `node_modules`, `venv`, `site-packages`, `build` or `dist`,
  are not listed and are never a candidate at boot. Keep notebooks and the
  modules they import in normally named paths.
- The URL is printed (default `http://127.0.0.1:7180`). Give it to the person.
- To try it: `sca example u_link` copies a motor-mount workspace (two parts and
  the assembly that fixes them together) to `./u_link_motor_mount`, then
  `sca edit ./u_link_motor_mount`.

## Edit cells through the editor: `sca cell`

```bash
sca cell ls [--code]                 # numbered cells with status, errors and output
sca cell get 3                       # one cell: code, status, errors, output
echo 'L = 90' | sca cell put 3       # replace the code of cell 3 and run it (--no-run to only save)
sca cell insert --after 3 -f new.py  # add a cell (--after start|end|CELL, --name fn_name)
sca cell rm 4
sca cell run [CELL ...]              # run cells (default all) and what they feed
sca cell open other.py               # have the editor open another notebook (waits for its kernel)
sca new bracket --kind part          # a new notebook; the open editor lists it, the person's view stays
```

- A cell is named by its number in `sca cell ls`, its `key`, its function name, or its id.
  Numbers move when cells are added or removed: read the list the command prints back.
- Each write prints the touched cell's state (`status`, `errors`, `output`). That is the
  feedback: read it before the next step, as with any other operation.
- `put` fails with a conflict if you pass a base that is out of date; without one it
  replaces the cell, so `get` first when the person may have changed it.
- The commands find the running editor through `<workspace>/.sca-editor/server.json`. With no
  editor running, or with another notebook open, `ls` and `get` read the file and the write
  commands refuse: run `sca cell open NOTEBOOK` (or pass `--open` to switch and write in one
  step), or edit the file directly, nothing else holds it.
- `@app.function` cells cannot be changed this way; edit them in the file.

## Read what the person is doing

| Need | Where |
| --- | --- |
| What is selected | the cell headed `# ---- selection ----` in the notebook file |
| Everything at once (selection, cell states, errors, parameter values) | `sca snapshot [WORKSPACE]`, or `<workspace>/.sca-editor/snapshot.json` |
| What the viewport looks like | `sca viewport [WORKSPACE] [--out PATH]` — the PNG's path, age and size, copied out with `--out` (the file is `<workspace>/.sca-editor/viewport.png`) |
| Which notebook is open | `notebook` in the snapshot |

`sca snapshot` only has an answer while the editor runs; it reports the last
state the editor wrote. If the snapshot is old (`updated`), ask the person to
move the viewport or re-select, or read the notebook file instead. (Unattended: read the notebook file.)

## The selection cell

Every pick in the viewport (Ctrl/Cmd+click adds) rewrites one cell:

```python
# ---- selection ----
# edge (of u-link-motor-mount, node node/u_link)
selected_edge_1 = scad.ql.edges().where(scad.ql.and_(
    scad.ql.prop("geom.type", "==", "CIRCLE"),
    ...
)).exactly(1)
selected_edge_2 = scad.ql.edges().where(...).exactly(1)
selected_item = [selected_edge_1, selected_edge_2]
```

- One variable per picked entity: `selected_<kind>`, or `selected_<kind>_<i>`
  when several of a kind are picked; `kind` is solid, face, edge or vertex.
  `selected_item` lists all of them in pick order. An empty selection is
  `selected_item = []`.
- Each selector is built from the entity's geometry (type, centre, size), not
  from an id. It keeps selecting the same place while the model is edited, as
  long as that geometry stays put. `.exactly(1)` fails loudly if the geometry
  moved away, which is the right signal.
- The cell is rewritten at every pick, so **do not put your code in it**.
  Build on it from a cell below it or from the cell that makes the feature:

  ```python
  # ---- feature: edge-chamfer (modifier) ----
  body = scad.chamfer_rsolid(solid=body, edges=selected_edge_1, distance=1.0)
  ```

- A selector says where, not what: confirm before changing geometry. Resolve it
  and print small QL facts (count, a measurement) per the global rules. If it
  matches nothing the person's model changed since the pick: ask them to pick
  again rather than guessing. (Unattended: no selection will arrive; derive the selector from the task's evidence, print
  its card, and record it in the report.)
- Do not rename `selected_*` variables or delete the cell; the editor finds it
  again by its first line. When the person is done with the selection, they
  clear it themselves.

### Turning "do X to the selection" into an edit

1. Read the selection cell and the snapshot (`kind`, how many).
2. Find the cell that owns the geometry (the feature cell that made the body the
   selection lies on, by its `# ---- feature: <slug> ----` header).
3. Add a feature cell after it, or edit the owning cell, using the selectors by
   name. Keep one feature per cell; give it a feature header.
4. Save the file. The editor shows the change (cells you edited show `stale`
   until run). Ask the person to run it, or run `sca run <notebook>` yourself
   to check the model builds, and read the errors. (Unattended: always `sca run`.)

## Cell references

The copy button on a cell's header puts a reference on the person's clipboard,
for pasting to you:

```
/path/to/u_link.py:L47-L48 (cell 02 `guard: parameter feasibility (REQUIREMEN`)
```

(Alt/Shift+click adds the cell's code in a fenced block.)

- `path:Lstart-Lend` is the cell's lines in the file; `cell NN` is its position
  in the notebook, and the backticked title is the feature slug, params header
  or first variable. Trust the path and lines; re-read them in the file, since
  they move when cells above are edited.
- "Change this cell" means edit those lines in place. Do not add a duplicate
  cell and leave the old one running.
- `@app.function` cells are shown as `function` and are read-only in the
  editor (marimo would turn them into plain cells if edited there). Edit them on
  disk; the editor reloads.

## Parameters

- A `# ---- params ----` cell lists parameters, each optionally with a trailing
  `# ui:` comment that sets the control: `slider(min, max, step=)`,
  `number(...)`, `toggle()`. Declare the controls you want the person to tune;
  without a comment a number gets a number box and a bool a toggle.
- Shared dimensions in a local module (`from dimensions import DIMS`) show in
  the workspace tab under *modules*. A module opens in a module view with its
  dataclass fields (and constants with a `# ui:` comment) as controls; a change
  reloads the module and reruns what imports it. Editing the module file from
  disk does the same.
- A slider **does not edit the file**: the value is saved in the notebook's state
  directory and the cells that read it rerun. The person's tuned values apply
  in the editor only; `sca run` ignores them unless given `--set NAME=VALUE`.
  When the person likes a value, they use **Write to source**, or you change
  the source. Do not treat the number in the file as what they see on screen:
  check `params` in the snapshot.

## The log dock

The bottom dock lists what ran and what failed (with times), and during a
re-evaluation shows how many cells are done and which one is running.
Errors there are the same errors `sca snapshot` reports per cell. A module that
does not compile is reported as `setup failed` with the file and line; fix that
file first, since every cell is blocked until it compiles.

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
- A blank notebook (`sca new NAME --kind blank`) has no cells and a `kind = "part"` header: no product cell is written,
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
- Workplanes: with a selection, Space (or the command "Workplane from selection") writes a `workplane` feature
  (`# ---- feature: wp (datum) ----`, `wp = scad.make_workplane_*_rworkplane(...)` with the picks resolved inline, offset
  and flip in the params cell). One flat face -> on it; a face and an edge -> x along the edge; two parallel faces ->
  the midplane; three vertices (in pick order) -> through them; one edge -> through it, turned by an angle. The new
  workplane becomes the active one (the camera turns to it, it is drawn blue); a new sketch goes on it, and the plane
  chooser lists every workplane variable. Each workplane variable of the notebook (GUI or code) is drawn as a small
  labelled patch at the frame the kernel computed (the server's `workplanes` envelope).
- A sketch on a workplane has `plane={"workplane": "wp", origin, x_axis, y_axis}` in its `# gui:` document and
  `plane=wp` in its code: the frame in the document is only for drawing before the cell runs; the cell follows `wp`.
  A workplane cell reads the body without consuming it (the body stays the open body / product).
- Unattended: the buttons are not available; write the cells yourself (see `discipline/notebook-cell-design.md`).

## The same operations from the command line

An agent does not click: `sca feature` and `sca sketch` do what the buttons do, with the same checks, as JSON in and JSON out.

```bash
sca feature specs [SPEC]             # operations and their typed slots (lengths mm, angles deg, bodies by name)
sca feature ls                       # features, bodies, tip, product, defaults
sca feature add box --name base --values '{"width": 40, "height": 30, "depth": 20}'
sca feature add fillet --values '{"radius": 2}' --selections '{"edges": [{"kind": "edge", "entity_id": "entity/..."}]}'  # named by the kernel; geometry-only items keep the older recipe
sca feature edit base --values '{"width": 50}'      # a GUI feature; a code feature is refused
sca feature rm base | sca feature undo | sca feature redo
sca sketch ls | get CELL | put CELL -f doc.json | solve CELL
sca sketch op CELL trim --args '{"entity": "h", "at": [8, 0]}' [--dry-run]
sca sketch op CELL extend --args '{"entity": "h", "end": "end"}'
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
- Errors name ids (`there is no entity 'x'`, `nothing is ahead of the end of h`); fix the call, do not retry it unchanged.
- Everything a command writes is an ordinary cell; `sca cell` still works on it (see the `# gui:` rules above).

## Rules of thumb

- Re-read the cell before editing (`sca cell get`, or the file): the person edits and
  autosaves too, and the editor rewrites the selection cell.
- Edit by cell, with `sca cell`. A change that touches many cells at once makes the person's
  screen reflow and loses their place.
- New notebooks: `sca new`, not a bare file write plus a request to refresh; the editor
  lists a new file by itself either way.
- After an edit, say which cells you changed (by reference) and what to look
  at, so the person can run them and judge the result.
- Never edit `__marimo__/` or `.sca-editor/`; both are generated.
- The editor only models. Exports and packages come from `sca run` /
  `sca export`, not from the editor.
