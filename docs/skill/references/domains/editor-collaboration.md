# Editor collaboration: working with a person in `sca edit`

Use this domain when a person has the code-first editor open (`sca edit`) and
you work on the same notebooks: they click, drag and tune; you read files and
edit code. It is not a workflow. The modeling you do still follows the workflow
you selected; this page says how to see what the person sees and how to hand
work back.

The notebook file is the only shared state. The editor autosaves every edit to
it, and every message the person gives you (a selection, a cell reference, a
tuned value) is also something you can read from disk. Never rely on what the
person says they selected when the file or the snapshot can tell you.

## Start the editor for a person

```bash
sca edit <workspace>          # a directory of notebooks, or one notebook
sca edit <workspace> --no-browser --port 7180
```

- Needs the `editor` extra (`pip install "simplecadapi[editor]"`); without it
  the command says so and stops.
- The workspace is any directory tree. Models are the notebooks whose header has
  `[tool.simplecadapi]`; assemblies list the parts they `use(...)`. Open the
  assembly to see the product, a part to edit that part.
- The URL is printed (default `http://127.0.0.1:7180`). Give it to the person.
- To try it: `sca example u_link` copies a motor-mount workspace (two parts and
  the assembly that fixes them together) to `./u_link_motor_mount`, then
  `sca edit ./u_link_motor_mount`.

## Read what the person is doing

| Need | Where |
| --- | --- |
| What is selected | the cell headed `# ---- selection ----` in the notebook file |
| Everything at once (selection, cell states, errors, parameter values) | `sca snapshot [WORKSPACE]`, or `<workspace>/.sca-editor/snapshot.json` |
| What the viewport looks like | `<workspace>/.sca-editor/viewport.png` (a PNG; look at it) |
| Which notebook is open | `notebook` in the snapshot |

`sca snapshot` only has an answer while the editor runs; it reports the last
state the editor wrote. If the snapshot is old (`updated`), ask the person to
move the viewport or re-select, or read the notebook file instead.

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
  again rather than guessing.
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
   to check the model builds, and read the errors.

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

## Rules of thumb

- Re-read the file before editing: the person edits and autosaves too, and the
  editor rewrites the selection cell.
- Edit by cell. A change that touches many cells at once makes the person's
  screen reflow and loses their place.
- After an edit, say which cells you changed (by reference) and what to look
  at, so the person can run them and judge the result.
- Never edit `__marimo__/` or `.sca-editor/`; both are generated.
- The editor only models. Exports and packages come from `sca run` /
  `sca export`, not from the editor.
