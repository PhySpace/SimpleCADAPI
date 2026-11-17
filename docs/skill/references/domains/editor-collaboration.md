# Editor collaboration: working with a person in `sca edit`

**Read when:** a person has the code-first editor open (`sca edit`) and you edit the same notebooks (a selection, a cell reference or a tuned value arrives).

This is not a workflow: the modeling you do follows the workflow you selected. This page says how to see what the person sees
and how to hand work back. The rules that matter:

1. **Unattended** (no person, no editor): do not start `sca edit`. Edit the notebook file directly, check it with
   `sca run <notebook>` and read its report instead of the snapshot, the viewport image or a selection cell. Never wait for
   a person to run, pick or tune anything (`discipline/operating-modes.md`).
2. **A person has the editor open:** it holds the open notebook in memory and is the one writer of its file, so **`sca cell`
   is the only way to change a regular cell** (`sca cell ls|get|put|insert|rm|run|open`, below). Writing the file behind its
   back races its next save and the page's version or yours is lost. Edit the file directly only when no editor runs, or for
   the setup cell and `@app.function` cells, which `sca cell` refuses: the editor takes those file changes in.
3. **`sca cell` finds the editor itself**, from the current directory. The editor's own `/api/health` answer is the truth
   (a process id is never consulted for a live one; a sandbox cannot see it). If it cannot, read the message:
   - `… does not answer`: no editor listens at that url. Start one (`sca edit`); do not delete records or reuse its port.
   - `answers for workspace X, not Y`: that port now belongs to another project's editor. Never send it your edits.
   - `N editors serve …`: several are live and none is chosen for you; pin one (next point).
4. **Pin an editor** when more than one can run: `--editor URL --instance ID` on any `sca cell`, `sca feature`, `sca sketch`
   or `sca new` command, or `SCA_EDITOR_URL` and `SCA_EDITOR_INSTANCE` (both are needed). The values are the editor's
   `SCA_EDITOR_READY {"url","instance","workspace","pid"}` line, printed once it listens. A pinned editor is used wherever
   the command runs, checked against its instance id, and never replaced by reading the file.
5. **Every report says which editor answered** (`editor`: url, workspace, instance). With several editors, read it before
   you trust a write.
6. **The notebook file is the shared state**, and the editor autosaves every edit to it. Never rely on what the person
   says they selected when the file or the snapshot can tell you.
7. **Your version wins** over a cell the person has open with unsaved typing: their text is dropped and kept in the editor's
   log for them. Do not rewrite a cell the person is typing in without telling them.

```bash
sca edit <workspace> --no-browser     # port 0 (default): the system picks a free one; --port N fixes it
sca cell ls --editor http://127.0.0.1:41233 --instance 3f9c2a7d41b0
```

### What the editor does with a file edit

The editor notices a saved change within a second, compares it with its cells and applies only what differs (changed cells
are edited in place and run again, added or removed cells appear or go away). A change to the setup cell or an
`@app.function` cell restarts the kernel instead. A file that does not parse is ignored until the next save that does.

## Start the editor for a person

```bash
sca edit <workspace>          # a directory of notebooks, or one notebook
sca edit <workspace> --no-browser --port 7180   # a fixed port; the default 0 lets the system pick a free one
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
- The URL is printed, and once the editor listens one line `SCA_EDITOR_READY {"url", "instance", "workspace", "pid"}`
  goes to stdout (the port is whatever the system picked unless `--port` is given). Give the URL to the person.

- To try it: `sca example u_link` copies a motor-mount workspace (two parts and
  the assembly that fixes them together) to `./u_link_motor_mount`, then
  `sca edit ./u_link_motor_mount`.

### Several editors at once

Each editor has its own instance id and its own record, `.sca-editor/editors/<instance>.json`, so editors never share or
delete one another's file (an editor removes only its own when it stops). Discovery takes the nearest workspace above the
current directory that has a live editor; a record counts only if `/api/health` answers with that record's workspace and
instance. Records that do not answer are an error only when no live editor is found. Editors on one workspace are allowed,
but they write the same notebooks: two writers is the person's decision, and `sca snapshot` / `sca viewport` read files
per workspace, not per editor, so the last editor to write wins there.

## Edit cells through the editor: `sca cell`

```bash
sca cell ls [--code]                 # numbered cells with status, errors and output
sca cell get 3                       # one cell: code, status, errors, output
echo 'L = 90' | sca cell put 3       # replace the code of cell 3 and run it (--no-run to only save)
sca cell insert --after 3 -f new.py  # add a cell (--after start|end|CELL, --name fn_name)
sca cell rm 4
sca cell run [CELL ...]              # run cells (default all) and what they feed
sca cell open other.py               # have the editor open another notebook (waits for its kernel)
sca new bracket --kind part          # a new, empty notebook; the open editor lists it, the person's view stays
```

- A cell is named by its number in `sca cell ls`, its `key`, its function name, or its id.
  Numbers move when cells are added or removed: read the list the command prints back.
- Each write prints the touched cell's state (`status`, `errors`, `output`). That is the
  feedback: read it before the next step, as with any other operation.
- `put` fails with a conflict if you pass a base that is out of date; without one it
  replaces the cell, so `get` first when the person may have changed it.
- The commands find the running editor as in rule 3 above. With no
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

## When a step fails: the model before it

A cell that fails (a parameter change that breaks a fillet, an edit) leaves no
values, and the cells after it do not run, so the product is not made. The
viewport then shows **the model before the failing step**, not the last model
that built: for a part notebook the open bodies of the cells that are left (the
body the failing feature was applied to); for an assembly built up over cells,
the assembly before the failing cell. A red notice in the viewport says which
step failed and why, and the snapshot carries it as `partial`:
`{failed: [{cell, name, status, error}], skipped: [cell ids that did not run],
shown: [bodies on screen]}` (`null` when the model is whole). Fix the failing
cell; the whole model replaces it. When nothing before the failing cell makes a
model (a broken params cell, an assembly made in one cell), the last model stays
on screen and the error names the failing cell. Exports never use a partial
model: they fail until the cell is fixed.

## Features the person made with buttons

Cells with a `# gui:` line, the `sca feature` / `sca sketch` commands, sketches, workplanes and `scad.ref` selections
made in the editor: read `editor-gui-features.md`.

## Rules of thumb

- Re-read the cell before editing (`sca cell get`, or the file): the person edits and
  autosaves too, and the editor rewrites the selection cell.
- Edit by cell, with `sca cell`. A change that touches many cells at once makes the person's
  screen reflow and loses their place.
- A notebook the person deletes in the workspace tab (manual or code mode) is moved to
  `<workspace>/.sca-editor/trash/<time>-<name>.py`, not erased; the open one is closed by opening another
  first. Look there before recreating a notebook the person says they lost.
- New notebooks: `sca new`, not a bare file write plus a request to refresh; the editor
  lists a new file by itself either way.
- After an edit, say which cells you changed (by reference) and what to look
  at, so the person can run them and judge the result.
- Never edit `__marimo__/` or `.sca-editor/`; both are generated.
- The editor only models. Exports and packages come from `sca run` /
  `sca export`, not from the editor.
