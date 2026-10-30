# Discipline: Notebook Cell Design

Where the cell boundaries go, and when a number is a `scad.var`. Read it with
`feature-tree-convention.md`: that file says what a feature block is and how it
is headed; this one says how to cut a notebook into cells and why. Every rule
carries its reason and the symptom you see when you break it, so you can
decide the cases the rules do not name.

## How a notebook runs (the facts the rules rest on)

1. **Dataflow, not order.** A cell runs when a name it reads has a new value.
   Cells that do not read the changed name are left alone.
2. **The cell is the unit of caching.** What a cell returns is its cached
   value: with the same code and the same inputs it is restored instead of
   run (from memory in the editor's kernel, else from the disk cache).
   Restoring costs time in proportion to the size of the value: each of the
   six-axis arm's assemblies (dozens of parts) takes about a second to read
   from the disk cache.
3. **A name has exactly one defining cell.** Two cells that define `body`
   fail with `MultipleDefinitionError: This app can't be run because it has
   multiple definitions of the name body`.
4. **A name that starts with `_` belongs to its cell.** Other cells cannot
   read it and it is not cached. Reading it elsewhere fails with
   `NameError: name '_tool' is not defined. Did you mean:
   '_cell_d4365cc9-Hbol_tool'?` — the suggestion is misleading; the fix is to
   make the name public and return it.
5. **A failure stops at the cell that raises.** Everything upstream stays
   cached, so the next run starts from the last good cell.

## Cell rules

**C1. One feature per cell.** The cell holds the construction of the
feature's tools and profiles plus exactly one operation that rebinds the body
(see the feature tree convention). *Why:* an edit or a parameter change
re-runs that feature and the ones after it, and a failure names one cell.
*Symptom if broken:* a change redoes work it did not need to, or an error
points at a cell that holds four features.

**C2. Keep a selector in the cell that uses it.** Resolve a QL selector
against the shape the cell receives, in the same cell as the operation that
applies it; do not return a selection for another cell to use. *Why:* a
selector resolved against an earlier state of the shape matches nothing or the
wrong entities (the SDK lists "the selector was resolved against an older shape
state" among the causes of a count mismatch).

**C3. Fragile or slow operations get their own cell, last in their group.**
Fillets, chamfers, shells, large booleans, patterns: follow
`feature-ordering.md`. *Why:* a failure there leaves everything before it
cached, and you retry only that cell.

**C4. Merge cells only for things that are cheap and always edited together**
— a sketch and the extrusion of that same sketch are one feature anyway. Do
not merge two features to save a cell. *Why:* a cell costs one cache lookup,
which is small; a merged cell re-runs both features on every edit, and a
failure names neither.

**C5. Never split one feature across cells.** Sketch, profile and tool
temporaries are `_private` names inside the feature's cell. *Why:* a value
returned from a cell is cached and shared; a temporary used once is not worth
that, and returning it clutters the namespace with names that are not part of
the feature tree.

**C6. Whatever another cell needs is public, returned, and named for what it
is.** `base_plate`, not `body` or `shape2`; the slug of the block in
snake_case. *Why:* every top-level name has one defining cell (fact 3), and
the names are the feature tree that a person and the next edit read.

**C7. Do not change a value you received.** `apply_tag(...)`,
`set_metadata(...)` and `auto_tag_faces(...)` change the shape they are given
and return that same object. Call them in the cell that makes the shape, or in
an `annotate` block that returns the result under its own new name and is the
only cell that touches those tags. *Why:* the producing cell
keeps its value in memory, and a later cell that tags it changes that object;
the copy on the disk does not have the change. The editor notices and reads the
disk copy instead, so a cell that tags what it received costs you the
speed-up of the cell it tagged.

**C8. Parameters live in their own cell(s) at the top, and hold no geometry.**
Group them by meaning (`# ---- params: flange ----`). *Why:* each reader
depends only on the parameters it reads, so many parameters in one cell cost
nothing; a geometry line in the params cell would re-run with every parameter
change.

**C9. The product is made in the last cell.** Its id is the notebook id
(`scad.notebook_id()`); a family of parts uses `scad.use(path, id=...)`.

**C10. In an assembly notebook, one `scad.use(...)` per child, the mates in
their own cell, the solve in its own cell.** Do not carry the whole assembly
through a chain of cells that each return it. *Why:* every cell that returns
the assembly caches a full copy of it (fact 2).

**C11. Make every edit step leave the names consistent.** A cell that reads a
name nothing defines fails, and so do all cells after it. The `sca new`
template has a params cell with `RADIUS` and `HEIGHT`, a `base` cell that
reads them, and a product cell that reads `base`. Replacing the params cell
with `sca cell put 1` while `base` still reads `RADIUS` fails with `NameError:
name 'RADIUS' is not defined` until `base` is replaced too. Replace or delete
the cells that read a name before, or in the same step as, the cell that
defines it; when no editor is running, write the whole file once.

## `Var` or a plain value

A `scad.var(name, default, unit=..., comment=..., tolerance=...)` is a named
design parameter. What it does, and what it does not:

- **It converts to millimetres and degrees when it is evaluated.**
  `scad.var("l", 2.0, unit="in")` evaluates to 50.8.
- **It checks units inside an expression when the expression is evaluated.**
  Adding a length and an angle raises `UnitValidationError: ... requires
  matching dimensions; got Length and Angle`. Mixing a variable that has a
  unit with one that has none raises `UnitValidationError: ... mixes
  unit-declared variables with legacy variables that have no unit`.
- **It does not check where you pass it.** An angle `Var` given as a radius is
  accepted and builds a solid; name the variables so a mistake is visible
  (`BORE_D`, `TAPER_ANGLE`).
- **Arithmetic on it builds a formula** (`2 * math.pi * R` is an `Expr`) that
  operators and QL predicates take as it is. Comparisons, `int()`, `round()`,
  `range(n)`, `max()`, f-strings and indexing read the value it has now.
  `bool(var)` raises (write `if R > 0:`); numpy and `json.dumps` need
  `float(R)`. See `docs/guides/notebook-runtime.md`.
- **It shows in the editor** with its unit, comment and `# ui:` control, and
  `sca run --set NAME=VALUE` overrides it. A plain number in a params cell
  does both of these too.

**V1. Make a `Var` for a dimension or an angle that comes from the
requirement or that a person might tune.** Diameters, lengths, thicknesses,
angles, clearances. Give each a unit and a comment.

**V2. Use a plain value for anything that is not such a dimension.** Counts
(`BOLTS = 6  # ui: number(3, 12, step=1)`), booleans, choices, indices,
selector tolerances (`0.999`), overlap and overshoot margins that keep a
boolean clean, sample counts. *Why:* a count has no unit and no tolerance; a
`Var` for it adds nothing, and `range(n)` needs a whole number.

**V3. A derived dimension is an expression of the variables, not a new
variable.** `BORE_R = BORE_D / 2` stays a formula of `BORE_D`. Put it in the
params cell when several cells use it or it states a design relationship; keep
it in the feature cell as a `_private` name when only that cell needs it.
*Why:* a second `Var` that holds a copied value drifts from the first without
any error.

**V4. Give every `Var` a unit, and do not mix unit and unitless variables.**
The second raises (above).

**V5. Pass the `Var` itself to operators and QL predicates.** Use `float(...)`
only where a plain number is required: numpy, `json.dumps`, and a notebook
that must also run on SimpleCADAPI 2.2.6.

**V6. Choose the `Var`'s name once.** `scad.var("plate_t", ...)` renamed to
`"plate_thickness"` is a different parameter to the cache: every cell that
reads it re-runs. Use a stable snake_case name.

## Before you hand over a notebook

- Every cell is one feature block with its `# ---- feature: ... ----` header,
  and the products and params cells are where C8 and C9 say.
- No name is defined in two cells; every temporary is `_private`; every name a
  later cell reads is returned by the cell that defines it.
- No selector is resolved in one cell and used in another.
- No cell calls `apply_tag`, `set_metadata` or `auto_tag_faces` on a shape it
  received, except the single `annotate` block that owns those tags.
- Each dimension a person would tune is a `Var` with a unit and a comment; every
  count, flag and margin is a plain value; no dimension is stored twice.
- The notebook runs from the top (`sca run --no-cache`) and again with the
  cache, and both runs report the same part.
