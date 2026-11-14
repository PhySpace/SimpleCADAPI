# Task Domain: Engineering Drawing Generation

**Read when:** a validated part or product needs a GB-standard drawing sheet (DXF + PNG).

Generate GB-standard 2D engineering drawing sheets (DXF, plus a PNG rendered
from that DXF for review) from finished 3D geometry with the declarative
`simplecadapi.dxf_engine` namespace. Standards followed: GB/T 4458.4-2003
(dimensioning), GB/T 4457.4-2002 (line types), GB/T 14692 (projection),
GB/T 4458.1 (hidden-line removal), GB/T 17452 (sections), GB/T 131 (surface
texture), GB/T 14689/14690 (sheet sizes, scales).

## Use when

- The part or product geometry is already modeled and validated, and the
  deliverable is a manufacturing drawing sheet.
- You need a first-angle multiview layout (长对正 / 高平齐 alignment), section
  views, a datum system, and dimensions placed by rule rather than by hand.

## Do not use

- For 3D visualization or geometry inspection — use the
  `simplecadapi.inspect.brep` rendering functions instead.
- As a modeling aid: the engine consumes finished shapes; it does not record
  graph nodes and does not modify geometry. Validate geometry first, draw
  second.
- For hand-placed annotation: callers never specify sheet coordinates. Sheet
  placement is owned exclusively by the solver.

## Core idea: reference the model, declare, solve, read the issues

`SheetDecl → SheetPlan.solve() → issues()/report() → render()`.

**A dimension measures model geometry, not typed coordinates.** Say what is
measured with a reference; the number on the sheet is the measurement, and it
follows the model when a parameter changes.

```python
import simplecadapi as scad
from simplecadapi import ql
from simplecadapi.dxf_engine import DimDecl, SheetDecl, SheetPlan, ViewDecl

bore = ql.faces().where(ql.and_(ql.prop("geom.type", "==", "CYLINDER"),
                                ql.prop("geom.center.x", ">=", -0.1),
                                ql.prop("geom.center.x", "<=", 0.1)))
decl = SheetDecl(
    title="Plate", dwg_no="P-001", scale=None, front="top", anchor=None,   # None: chosen by the engine
    views=[ViewDecl("top", part, (0, 0, 1), (1, 0, 0)),                    # pass the solid, not part.wrapped
           ViewDecl("sec", part, (0, -1, 0), (1, 0, 0),
                    align={"to": "top", "side": "below", "gap": 30.0},
                    section=(0, 0, 0), label="A", mark_in="top")],
    dims=[DimDecl("overall", "top", "linear", "W", extent="x"),
          DimDecl("size", "top", "diameter", "d_bore", of=bore, tol=(0.021, 0.0), fit="H7"),
          DimDecl("overall", "sec", "linear", "T", extent="y")])
plan = SheetPlan(decl).solve()
print(plan.report())                 # read the Issues section before rendering
plan.render("plate.dxf", "plate.png")
```

| You measure | Declare | A reference is |
| --- | --- | --- |
| a hole or shaft diameter, a fillet radius | `of=ref` | a circular edge or a cylinder face (seen along its axis; a diameter also from the side: it becomes a `⌀` dimension between the two outlines) |
| a distance | `between=(ref, ref)`, optional `axis="x"\|"y"` | a vertex, a straight edge, a plane face seen edge-on, a cylinder (its axis), a model point `(x, y, z)` |
| the overall size of the view | `extent="x"\|"y"` | — |

A reference is an SDK entity (`Face`, `Edge`, `Vertex`), a QL selector that
resolves to exactly one entity of the view's solid, or a 3D point. A reference
the view cannot show (a face not seen edge-on, a selector with 0 or 2 matches)
raises `RefError` with what to reference instead. The typed forms
(`p1`/`p2`, `center`/`radius`, view-local coordinates) remain for geometry the
model does not have; they are checked against the figure lines.

Text of a dimension: `[count×][prefix][⌀|R]number[tol][ fit]`. `value=` is
what you expect: a difference from the measurement is an error, and the sheet
shows the measurement. `show_captions=True` appends `(caption)` for review.

## What the engine does without being told

- Scale (`scale=None`: the largest GB/T 14690 scale that fits) and position
  (`anchor=None`: centred in the free area); `sheet="A4"…"A0"`.
- Centre lines of every hole and shaft, from the model's cylinders
  (`auto_centers`), interrupted where a text stands on them.
- Side of a linear dimension (nearest the measured geometry), row order (small
  inside, large outside), extension lines from the edge end nearest the line.
- Diameter text inside the circle when it fits, on the extended line outside
  when not; arrows from outside on small circles.
- Section views: cut, hatch (ANSI31), no hidden lines, title `A-A`,
  cutting-plane symbol in the `mark_in` view.
- Native DXF `DIMENSION` entities (style `GB`, `DIMLFAC = 1/scale`) that a CAD
  program can edit; after writing, the file is read back and every dimension
  is compared with the model.

## Issues: the one truth

`plan.issues()` returns `Issue(code, severity, element, message, hint, data)`;
`report()` prints the same list, and the diagnostic picture
(`SheetDecl.diag_png`) is drawn from the same evaluation. Fix errors, fix or
accept warnings, read the "Not checked" list: no issue is not a correct drawing.

| Kind | Codes |
| --- | --- |
| placement (R1, R3) | `TEXT_OVER_TEXT`, `TEXT_OVER_FIGURE`, `LINES_CLASH`, `DIM_LINES_OVERLAP`, `IN_KEEPOUT_ZONE`, `OUTSIDE_FRAME`, `OVER_OTHER_VIEW`, `LINE_THROUGH_VIEW`, `DIM_TEXT_NEAR_VERTICAL` |
| truth | `DIM_VALUE_MISMATCH` (error), `DIM_NOT_ATTACHED` |
| completeness (R5–R7) | `UNDIMENSIONED_CYLINDER`, `OVERALL_SIZE_MISSING`, `PARAM_ONLY_IN_TABLE`, `DUPLICATE_DIMENSION`, `DATUM_UNDECLARED` |
| sheet | `VIEW_OUTSIDE_FRAME`, `VIEW_OVER_TITLE_BLOCK`, `VIEWS_OVERLAP`, `SHEET_UNDERUSED`, `SCALE_NOT_STANDARD`, `ROUGHNESS_UNREADABLE` |
| output (after render) | `DIM_RENDER_MISMATCH`, `DIM_MISSING_IN_FILE` |

When the solver finds no clean position it draws the least-conflicted one and
reports it. Then decide: re-declare (`side`, `row`, `at`, view gaps), or apply
actions — `plan.evaluate()` gives each conflicted element's obstacles and free
corridors; `plan.apply([{"op": "lin", "name": c, "side"/"row"/"slide": …},
{"op": "dia", "name": c, "at": deg, "mode": "inside"|"outside"},
{"op": "rad", "name": c, "at": deg, "s": mm}, {"op": "lead", "name": n,
"off": [dx, dy]}, {"op": "accept", "name": id, "reason": …}])` validates each
one and rejects with the obstacles (rollback). The action file is the
decision log.

## API groups

Read the exact page under `references/docs/api/` for every API used:
`SheetDecl`, `ViewDecl`, `DimDecl`, `DatumDecl`, `CenterDecl`, `LeaderDecl`,
`RoughDecl` (declarations); `SheetPlan` (`solve`, `issues`, `report`,
`evaluate`, `apply`, `render`, `tx`), `Resolved`, `Issue`, `RefError`,
`render_plan`.

## Known boundaries

- Linear dimensions are horizontal or vertical; no aligned, angular or
  chamfer dimensions.
- No threads, welds or geometrical tolerances; tolerance and fit values are
  drawn as declared, not checked against a standard.
- Completeness covers holes/shafts, overall sizes and declared parameters
  only: it does not prove the part is fully defined.
- One part per sheet set; no assembly balloons or BOM.
- HLR may emit arc edges as B-splines; such arcs render as polylines.

## Failure modes

- Typing coordinates where a reference exists: the dimension then does not
  follow the model. Use `of` / `between` / `extent`.
- Passing `part.wrapped` as `ViewDecl.shape` and a selector as reference:
  selectors resolve against the solid; pass the solid.
- Treating "0 issues" as "drawing is right": always review the PNG and the
  "Not checked" list; open the DXF in the target CAD program before release.
- Hunting for coordinates to fix a warning: there are none. Change the
  declaration or apply an action.
