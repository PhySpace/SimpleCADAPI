# The drawing engine: dimensions bound to the model, one truth for checks

Decision record for the rework of `simplecadapi.dxf_engine` (branch `feat/dxf-engine-bound-dimensions`, 2026-11-14).

## What started it

The owner's note: the drawing module "has never really been looked after, so its ability is poor"; outline and
hidden-line removal come from OCCT HLR, ezdxf draws dimensions and the rest; the design assumed a fully automatic layout
engine is not possible, so the engine judges where the layout is bad, renders a diagnostic picture, and the agent
adjusts. "There should be a better scheme." The owner asked for the experience of AgentCAD
(github.com/lizaixi01/AgentCAD, a 2D drawing runtime for agents on ezdxf) to be carried over, then said: do it.

## What was found (checked by running, 2026-11-14)

A plate 80 × 50 × 10 with four ⌀6 holes and a ⌀20 bore was drawn with the engine as it was:

| Finding | Evidence |
| --- | --- |
| `render("a.dxf", "a.png")` crashes after writing the DXF | `AttributeError: 'str' object has no attribute 'write_bytes'` |
| The report says R1–R7 all ok; the diagnostic picture marks 3 elements red | `rule_log` never received R1 entries; `evaluate` ran its own test |
| Texts stand on figure lines of their own view | `_text_clear(skip_view=own)` skipped the own view altogether |
| The checked box is not where the text is drawn | for a line pointing left the box ran along `u`, the text along the reading direction (`-u`); the linear evaluation used the baseline start as the box centre |
| `prefix="4×"` is not drawn on a diameter | the diameter text was built without `dcl.prefix` |
| The title block names a designer and a material nobody declared | `"GLM-Agent"`, `"PLA-CF / PAHT"` hard-coded |
| The plate thickness is on no figure; nothing says so | "parameter table" counted as covered |
| Text boxes are about 25 % narrower than the text | 0.62 h per character assumed; Arial measures 0.78 h |
| "Large outside" was the other way round | sort key `-abs(value)` gave the largest dimension the first (inner) row |
| A view below another overlaps it when its local y range is positive | `gap` was measured to the view's origin, not its edge |

Read in AgentCAD (source and its trial reports): native `DIMENSION` entities with measured text (`<>`) and a
bound-to-geometry check; selector targets for circles; validation attached to every edit with coded issues, exact
numbers and a fix hint; a read-back of the written file; reports of what was *not* checked; the measured lesson that
"7 of 7 runs validated themselves as passed, 5 of 7 had visible defects after plotting", and that agents fixed every
defect unaided once a check named it. AgentCAD has no 3D → 2D projection and no layout solver (its own report: layout
quality "unstable in both arms, and neither self-check catches it").

So the two projects are complementary, and the owner's original judgement holds: the engine cannot promise a perfect
layout, but it can promise a true one and an honest report. The better scheme is not a different loop; it is making
each half of the loop trustworthy.

## Decisions

**D1. A dimension measures model geometry; the number on the sheet is the measurement.**
`DimDecl.of` / `between` / `extent` take references (SDK entity, QL selector resolving to one entity, 3D point);
`refs.py` turns a reference into what the view shows of it (point, line, circle, band). `value` becomes the expected
value: a difference is `DIM_VALUE_MISMATCH` (error) and the sheet shows the measurement.
Why: typed `p1`/`p2` are only as right as the typing and do not follow a parameter change, while the SDK's whole point
is selecting geometry by what it is. Rejected: deriving dimensions fully automatically from the feature graph — which
sizes matter is a design statement; the engine proposes missing ones through checks instead (D4).
Kept on purpose: the typed forms, for geometry the model does not have, checked by `DIM_NOT_ATTACHED`.

**D2. One conflict test, one issue list.** `collide.conflicts` is asked by the solver, the evaluation and the actions;
`checks.collect_issues` is what `issues()`, `report()` and the diagnostic picture show. Text over figure lines of the
own view is a conflict; centre lines are not obstacles (they are interrupted under text at render, as the standard
says). Why: a report that says "ok" over a picture that shows red teaches the agent to trust neither.

**D3. What is checked is what is drawn.** One geometry derivation per kind (`lin_geometry`, `dia_geometry`,
`rad_geometry`) shared by solver and actions; text is placed by its box (`text_on_line`), so reading direction can no
longer part the two; text width is measured in the sheet's font.

**D4. Completeness and truth checks with a hint each, and a list of what is not checked.** Holes/shafts without a
diameter, overall sizes without a dimension, parameters only in the table, duplicates, unattached typed points, views
outside the frame. `NOT_CHECKED` is printed with every report. Why: AgentCAD's trials — agents repair what a check
names and miss what none names; "no issue" must not read as "correct".

**D5. Never an undrawn element.** When no candidate is clean the least-conflicted one is drawn and reported. Before, a
linear dimension without a free row lost its geometry and vanished from the DXF.

**D6. Native `DIMENSION` entities whose picture is ours.** Each dimension is a DXF `DIMENSION` in style `GB` with the
measured points as definition points, the measurement in group 42 and `DIMLFAC = 1/scale`; its anonymous block is drawn
from the solved geometry. After writing, the file is read back (`verify_dxf`). Rejected: letting ezdxf render the block
— its diameter renderer with a user text location produced a degenerate line in a trial, and its geometry would differ
from what the solver checked.

**D7. The sheet is derived unless declared.** `scale=None` picks the largest GB/T 14690 scale that fits, `anchor=None`
centres the views, `sheet` selects A4–A0, the notes area is as high as its content, the title block shows only declared
fields. `gap` is the clear distance between views. Dimension side defaults to the nearer side; small dimensions take
the inner rows.

**D8. More of a drawing.** Section views (`ViewDecl.section`: cut, hatch, no hidden lines, title, cutting-plane
symbol), centre lines from the model's cylinders, tolerances and fits on a dimension, surface-texture symbols
(`RoughDecl`, `general_rough`), a diameter on a cylinder seen from the side.

**D9. Module split.** `planner.py` (769 lines) became `planner`, `dims`, `leaders`, `collide`, `geom2d`, `bind`,
`refs`, `views`, `sheet`, `checks` (AGENT.md: plan for module splitting).

## What changes for a caller

- New: `of`, `between`, `axis`, `extent`, `tol`, `fit`, `count` on `DimDecl`; `section`, `label`, `mark_in` on
  `ViewDecl`; `RoughDecl`; `sheet`, `designer`, `revision`, `roughs`, `general_rough`, `show_captions`, `auto_centers`
  on `SheetDecl`; `SheetPlan.issues()`; `Issue`, `RefError`.
- Changed defaults: dimension text no longer carries `(caption)` (`show_captions=True` restores it); `dec=None` shows
  the decimals the value has (was 0: ⌀6.5 was drawn as 6); `material=""`; `notes_zone=None`; `align` gap is clear
  distance; diameter text is inside or outside the circle, never across it.
- `scale` and `anchor` may be `None`.
- `render()` returns a dict and takes str paths.

## Not done

Aligned, angular and chamfer dimensions; threads, welds, geometrical tolerances; assembly sheets (balloons, BOM);
checking tolerance values against a standard; plotting through a real CAD program in CI (AgentCAD's lesson says this
finds defects no in-process check does: worth doing next).

## Checked

`test/test_dxf_engine.py` (20) and `test/test_dxf_engine_bound.py` (21) pass, with `test_auto_docs_gen`,
`test_skill_lint`, `test_skill_build`, `test_drawing_skill_integration` (114 in all). Two sample sheets (the plate with
a section, a stepped shaft with a cross hole) were rendered and looked at: 0 issues, all dimensions read back equal to
the model. Run on macOS arm64 with the 2.3.0 wheel's native module under the repository's Python sources; the C++
sources were not rebuilt (nothing under `src/cpp` changed). Not verified: opening the DXF in AutoCAD or another CAD
program; Windows and Linux fonts (text width falls back to an estimate when the font cannot be loaded).
