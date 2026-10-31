# Task Domain: Engineering Drawing Generation

**Read when:** a validated part or product needs a GB-standard drawing sheet (DXF + PNG).

Generate GB-standard 2D engineering drawing sheets (DXF, plus a PNG rendered
from that DXF for review) from finished 3D geometry with the declarative
`simplecadapi.dxf_engine` namespace. Standards followed: GB/T 4458.4-2003
(dimensioning), GB/T 4457.4-2002 (line types), GB/T 14692 (projection),
GB/T 4458.1 (hidden-line removal).

## Use when

- The part or product geometry is already modeled and validated, and the
  deliverable is a manufacturing drawing sheet.
- You need a first-angle multiview layout (长对正 / 高平齐 alignment), a datum
  system, and size / position / overall dimensions placed by rule rather than
  by hand.

## Do not use

- For 3D visualization or geometry inspection — use the
  `simplecadapi.inspect.brep` rendering functions instead.
- As a modeling aid: the engine consumes finished shapes; it does not record
  graph nodes and does not modify geometry. Validate geometry first, draw
  second.
- For hand-placed annotation: callers never specify sheet coordinates. Sheet
  placement is owned exclusively by the solver.

## Core idea: declare, then solve

The engine is a four-layer pipeline with one-way data flow:
`SheetDecl (declaration) → SheetPlan.solve() (rule-driven solve) →
resolved/accepted/report() (audit) → render (DXF + PNG)`.

Callers declare *what* must be expressed — views, datums, dimension
semantics, center lines, leader notes — in view-local model coordinates. The
solver computes every sheet position under rules R1–R7 and records each
placement (and any least-adjustment deferral) in an auditable report.

## Solver contract (R1–R7)

| Rule | Contract |
| --- | --- |
| R1 safe zone | Text (OBB), leaders, and dimension lines must not collide with geometry, other annotations, or forbidden zones; least-adjustment deferral, never silent deletion |
| R2 text direction | Text parallel to the dimension line; heads up (horizontal) / left (vertical); never upside down |
| R3 30° dead zone | Dimension lines near vertical within ±30° produce a warning (GB/T 4458.4 fig. 17) |
| R4 row slots | Same-side dimensions use fixed row pitch; declared row wins, collisions defer outward; larger sizes land outer automatically |
| R5 parameter coverage | Every model parameter is carried by a dimension (`covers`) or lands in notes / parameter table |
| R6 datum reference | Position dimensions must reference a declared datum letter |
| R7 no duplicates | No repeated same-kind measurement within a view |

## API groups

Read the exact page under `references/docs/api/` for every API used:

- Declaration (pure dataclasses, validated at declaration time):
  `SheetDecl` (sheet: title, drawing number, scale, views, notes, parameter
  table), `ViewDecl` (HLR view: `n` view direction, `xd` screen-right,
  `align={"to","side","gap"}`), `DimDecl` (`kind=size|position|overall` ×
  `semantic=linear|diameter|radius`, `covers` for parameter traceability),
  `DatumDecl` (datum letters A/B/C…), `CenterDecl` (line or arc center
  lines), `LeaderDecl` (leader notes).
- Solve and audit: `SheetPlan(decl).solve()`, `plan.resolved`
  (`Resolved` items: requested → resolved, `adjust`, `draw`, rules),
  `plan.accepted`, `plan.report()` (auditable text report), `plan.tx(view,
  point)` (view-local model → sheet coordinates).
- Layout evaluation and actions (agent-in-the-loop): `plan.evaluate()` —
  structured per-element conflict report (`violations`: exact obstacles with
  distances; `corridors`: free translation ranges), digested quantities
  instead of raw geometry; `plan.apply(actions)` — replay an action-log JSON
  (`rad`/`dia`/`lin`/`lead` placement adjustments, `accept` to bless a
  warning with a reason) with per-action validation and reject-with-rollback
  residuals. The engine owns deterministic truth; the agent owns discrete
  choices. The action file is the decision log — plans rebuild statelessly
  from declarations plus replayed actions.
- Output: `SheetPlan.render(dxf_path, png_path)` / `render_plan` — GB layers
  (粗实线 / 虚线 / 中心线 / 细实线 / dimension / text), solid arrows,
  CJK-capable text style; writes the DXF and a PNG rendered from it for
  cross-checking.

See `references/workflows/engineering-drawing.md` for the staged workflow
that composes this domain.

## Known boundaries (preliminary engine)

- No section views or hatching yet.
- Linear dimensions are horizontal/vertical only.
- `DimDecl` carries no arc-span information, so radius/diameter labels place
  same-side outward (`out=6/12/18/24/30` ladder); there is no flip-to-opposite
  candidate. If it does not fit, R1 reports a warning — change the layout,
  not the rules.
- HLR may emit arc edges as B-splines; such arcs render as polylines.
- A boss circle can be drawn twice (visible compound + outline compound);
  key-based dedupe is pending.

## Failure modes

- Declaring a `position` dimension without `datum` raises `ValueError` at
  declaration time — this is intentional fail-fast (R6); declare the datum
  first.
- R1 warnings mean "does not fit as declared". Fix by re-declaring
  (`side`, `row`, `out`, view gaps), never by hunting for coordinates to
  nudge — there are none.
- Treating "no rule conflicts" as "drawing looks right": always review the
  PNG. Solver-clean sheets can still be visually wrong (e.g. an ambiguous
  view or a misleading dimension arrangement).
