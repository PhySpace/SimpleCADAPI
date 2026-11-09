# Discipline: Feature Tree Convention (FTC)

**Read when:** you author or edit any part source (every workflow): what a feature block is, its header and name.

Part sources are block-structured feature chains: every block is one feature
in the sense of a commercial CAD feature tree (Onshape / SolidWorks /
Fusion 360), readable by humans and LLMs, and translatable by the package
translators. This convention is mandatory for every part source authored in
any workflow.

A model is a marimo notebook (`docs/guides/notebook-runtime.md`), and each
block is one cell of it. Why the cell is the unit, and where cell boundaries go,
is in `notebook-cell-design.md` (rule C1 and the facts it rests on).

## The paradigm

A part is a chain of blocks, each block being one step of:

```text
sketch  →  basic body build op  →  bool  →  modifier
```

expressed as explicit dataflow — each application call rebinds the body:

```python
body = scad.sweep_rsolid(profile=..., path=...)      # build
body = scad.cut_rsolid(body, tools)                  # subtract
body = scad.union_rsolid(body, bosses)               # add
body = scad.fillet_rsolid(solid=body, edges=sel, radius=r)  # modify
```

There is no accumulator object and no hidden state: inputs are explicit,
the recorded graph mirrors the source structure, and a failed operation
names one feature.

Inside one builder function the blocks rebind one `body` name. Across
notebook cells they cannot — marimo forbids defining a variable in two
cells — so each cell binds the body under a name of its own (see
[Blocks are cells](#blocks-are-cells)).

## Block header comments (mandatory)

Every block opens with a boundary comment; the next header closes the
previous block. One block = its tool/profile construction + exactly one
application call that rebinds the body (the first `build` block returns it).

```python
# ---- feature: base-plate (build, profile=sketch) ----
# ---- feature: motor-pockets (subtract, profile=geometry) ----
# ---- feature: boss-columns (add) ----
# ---- feature: cable-windows (subtract, profile=sketch) ----
# ---- feature: global-fillet (modify) ----
# ---- feature: mount-face-names (annotate) ----
```

- Fixed parseable form: `# ---- feature: <slug> (<role>) ----`.
- `<role>` is a closed vocabulary: `build | add | subtract | intersect |
  modify | pattern | annotate`.
- `<slug>` is the stable identity of the feature — no sequence numbers
  (source order is the feature order; numbers rot when features are
  inserted or reordered).
- Add a tier annotation when the block constructs new 2D input:
  `profile=sketch|geometry` and/or `path=sketch|geometry`.
- Block-local helpers live next to the block and carry the slug in their
  name (`_motor_pocket_tools`).

## Tier rules — where each authoring API is legal

**Sketch tier (default).** Closed planar profiles consumed by extrude,
revolve, or loft sections are authored in the sketch API with constraints
carrying the design intent, promoted via `make_face_from_sketch_rface`.
Never transcribe hand-computed coordinates for a parametric profile —
tangency and relational dimensions are constraints, not arithmetic
(`constrain_tangent_rsketch(..., at_a=..., at_b=...)` replaces hand-derived
arc midpoints).

**Planar sweep paths are sketch tier.** A planar path (open chain) is a
constrained sketch promoted with `make_wire_from_sketch_rwire` —
closedness is a consumer contract, so an open chain promotes fine and
`sweep_rsolid` accepts it; extrude/revolve/face builders reject open
wires at the point of use. Annotate `path=sketch`.

**Geometry tier (only these three cases).**

1. Non-planar paths and 3D curves — `make_helix_redge`, 3D splines; the
   sketch API is planar-only. Annotate `path=geometry`.
2. Transcribed or imported geometry whose constraints are unknown
   (reverse engineering, dataset conversion). Annotate
   `profile=geometry` — honestly, so the lost intent is visible.
3. Pure tool bodies whose shape **is completely contained in a basic
   primitive form** — a cut box that is just a box, a boss column that
   is just a cylinder (`make_box_rsolid`, `make_cylinder_rsolid`).
   Primitives are legal exactly when the design shape is fully expressed
   by the primitive and nothing more; a primitive is never a shortcut
   for a profiled feature. If the shape needs a profile, author a sketch.

## Selections inside blocks

`modify` blocks select through QL selectors — predicates plus cardinality
(`.take(n).exactly(n)`) — or tags. Bare topology enumeration does not
exist (plural getters are index-only); selections that escape the graph
capture kernel artifacts and do not translate. Indexed picks are reserved
for intentional, named choices.

## Ordering and failure

Follow `feature-ordering.md` for block order (base → additive →
subtractive → shell → through-holes → fillets/chamfers last): fragile
operations late, one named feature per block so a failure localizes to
one header. Parameter guards (`assert`-style feasibility checks on
design parameters) stay in the source; geometric verification never does
— it lives in the external verification scripts per
`geometric-validation.md`.

## Blocks are cells

In a notebook every block is one `@app.cell`. This section owns what a block
looks like inside its cell (header and name); `notebook-cell-design.md` owns the
rest, each rule with its reason: one feature per cell (C1) and when cells may
merge (C4), `_private` temporaries (C5), the parameters cell (C8), the product
cell (C9), local-module imports (C12). Read it too.

- The block header is the first line of the cell body.
- The cell returns the body under the block's slug in snake_case
  (`base-plate` → `base_plate`), and the next block reads that name. The
  variable names then spell the feature tree, and an override
  (`sca run --set`) or a failure points at one feature. (Each block binds a new
  name because a notebook name has one defining cell: `notebook-cell-design.md`,
  fact 3.)
- A notebook that describes a part family names the product
  `scad.notebook_id()`, and each use gives the member its id
  (`scad.use("link_bar.py", id="crank", ...)`).

## Library parts: the `@scad.part` decorator

Parts reused by several notebooks live in plain `.py` modules as
`@scad.part` (or `@scad.assemble`) builders, their blocks inside the builder
function rebinding `body`. `@scad.part` accepts keyword parameters only;
emitted corpus sources state them explicitly so the meaning is legible from
the source itself:

- `id` — logical part identity (defaults to the function name).
- `revision` — `'1.0.0'` by default.
- `inputs` — sequence of `file_input()` declarations; the referenced files'
  content snapshots are recorded in the definition.
- `project_root` — anchor for file inputs and recorded source paths.
  Default: the directory containing the builder's source file, so a module
  runs from anywhere. Pass it explicitly only to anchor at a larger project.
- `tolerance_profile` — kernel tolerance fingerprint (default
  `'simplecad-default'`).

A builder never caches; each call builds afresh. How the calling cell is cached
is in `docs/guides/notebook-composition-and-cache.md`.

**Delivered sources state the anchor explicitly.** A translator-emitted
or standalone `.ftc.py` passes `project_root=Path(__file__).parent`
explicitly so the anchor is legible from the source itself — even though
it matches the default, the corpus states it rather than relying on
implicit resolution.

## Reference shape of a compliant source

```python
# /// script
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "motor-mount"
# revision = "1.0.0"
# ///
import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad
    from simplecadapi import ql


@app.cell
def _():
    # ---- params ----
    PLATE_T = scad.var("plate_t", 6.0, unit="mm")
    FILLET_R = scad.var("fillet_r", 1.0, unit="mm")
    ...
    return (FILLET_R, PLATE_T)


@app.cell
def _(PLATE_T):
    # ---- feature: base-plate (build, profile=sketch) ----
    _s = scad.make_sketch_rsketch(name="base", plane="XY")
    ...  # constrained rectangle, promoted to _face
    base_plate = scad.extrude_rsolid(profile=_face, direction=(0, 0, 1), distance=PLATE_T)
    return (base_plate,)


@app.cell
def _(base_plate):
    # ---- feature: motor-pockets (subtract, profile=geometry) ----
    _pockets = ...  # pure primitives: geometry tier
    motor_pockets = scad.cut_rsolid(base_plate, _pockets)
    return (motor_pockets,)


@app.cell
def _(FILLET_R, motor_pockets):
    # ---- feature: mount-fillet (modify) ----
    mount_fillet = scad.fillet_rsolid(
        solid=motor_pockets,
        edges=ql.edges().where(ql.and_(
            ql.prop("geom.type", "==", "CIRCLE"),
            ql.prop("geom.center.z", ">=", ...),
        )).exactly(2),
        radius=FILLET_R,
    )
    return (mount_fillet,)


@app.cell
def _(mount_fillet):
    motor_mount = scad.Part(part_id="motor-mount", body=mount_fillet)
    return (motor_mount,)
```

Each Onshape-style feature tree entry maps to exactly one header here —
that one-to-one mapping is the acceptance criterion for a compliant
source.
