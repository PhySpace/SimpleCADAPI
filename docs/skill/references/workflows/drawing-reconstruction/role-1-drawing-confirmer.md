# Drawing Reconstruction: Role 1, Drawing Requirement Confirmer

Part of `workflows/drawing-reconstruction.md` (outline, standing discipline, role map). Load when Role 1 starts.

## Role 1 — Drawing Requirement Confirmer ⛔

Convert the drawing into `drawing_work/report_A.md` and `REQUIREMENTS.md`.
No geometry, no probe builds, no source-file writes before this gate closes.

1. Copy the source PDF into `<part-dir>/drawing_work/source/` first
   (transfer directories expire). Run the parsing SOP steps 0–7 of
   `domains/drawing-inspection.md` exactly — checkup and route verdict, text
   coordinate preflight, inventory, overview pass, region reading, per-view
   calibration and measurement, separate association verification, semantic assembly.
2. If the route verdict is not `vector`, stop the route: name what is
   missing (raster-only sheet, mixed content) and ask the user for a vector
   PDF or the native DXF/DWG. Never improvise an OCR path.

**Unattended:** do not ask for a vector PDF. Record the blocker (the route verdict and what is missing) in the report,
stop this route, and build nothing from a non-vector sheet. `report.md` carries the route verdict and its evidence;
never improvise an OCR path and never invent the missing input.
3. Write `report_A.md` in the ten-section skeleton. Every dimension gets a
   stable `DIM-xxx` id and all ledger fields required by the inspection domain.
   Unresolved association prevents a verified verdict for that DIM; independent
   stages can continue. Every section view in the view list also
   records its resolved cut-plane spec (plane position, normal, viewing
   direction) per the Section-plane parsing rules (R1–R7) of
   `domains/drawing-inspection.md` — deterministic, never asked; a view
   whose plane cannot be resolved uniquely is marked `unreviewable` in the
   gap list. Unrecoverable content (external
   schedules, blank title fields, unlabeled constructions) goes to section 9
   verbatim — measured-and-marked where possible, listed as missing where
   not.
4. Refine the requirement into `REQUIREMENTS.md`
   (`domains/requirement-refinement.md`): units and coordinate convention
   fixed from the sheet's views (front view, up axis, datum story from the
   GD&T section), named parameters seeded from the dimension ledger,
   verification intent, export targets. Technical-requirement lines are
   classified: geometry-affecting (model) vs process/manufacturing notes
   (deliverable remarks, never modeled).
5. Batch every blocking item into ONE ask round: disputed shape-level
   interpretation, missing external schedules (e.g. curve coordinate
   tables), approximation approvals for sheet-unsupported geometry, and
   material assumptions where a check needs one. Record everything in the
   Ask-or-Record ledger with the user's wording preserved.


**Unattended:** there is no ask round (the host ask/question bindings below are skipped). Decide every blocking item
from the evidence (measured over prose over inference; the conservative option when the evidence ties) and write it in
the ledger as `value / evidence / how to change it / the check that would show it wrong`. Disputed shape-level
interpretation or an ambiguous view: take the reading whose association is verified, mark it 〔归属〕 and list the
alternative in report section 8. An unreadable dimension stays `unresolved` (quote the crop); it is modelled only from
an accepted-calibration vector measurement marked 〔推算〕, otherwise it goes to section 9 and its stage proceeds
without it. A missing external schedule is measured-and-marked or listed as missing, never invented. An approximation
for sheet-unsupported geometry is used only when needed, labelled 〔推算〕, and ledgered. A material assumption is
chosen, ledgered, and supports no strength claim.
<!-- skill:if omp -->

### Host binding: designing the Role 1 `ask` payload (omp)

One batched `ask` call for all items that block `REQUIREMENTS.md`. One
decision per question; name the region, view, or DIM id and state the
evidence or gap; options mutually exclusive and operational (what gets
recorded, what modeling follows); conservative clearly-labeled assumption
first with `recommended: 0` — a recommendation, never consent; include a
concrete correction path. Stable machine-readable `id`s keyed to ledger rows
(e.g. `arc_schedule_missing`, `unlabeled_hatched_circles`). After the call,
copy answers into the ledger verbatim; timeout or dismissal keeps the gate
blocked and stops — never continue by silently selecting the recommended
option.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: designing the Role 1 `question` payload (opencode)

One batched `question` call. No `id` field: key each ledger row to the
`header` (≤30 chars) derived from the stable identifier (e.g. `arc
schedule`, `hatched circles`); no `recommended` index: put the conservative
option first with a `(Recommended)` label suffix. Free-text custom answers
arrive automatically — phrase the question so the needed correction is
obvious when no option fits. Copy selected labels and custom answers into
the ledger keyed by header; a dismissed question is an unanswered blocking
row: keep the gate blocked and stop.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode,codex,dsh,kimicode -->

### Host binding: requirement questions using available host tools

Use the host's available question tool for the batched requirement questions;
if none is available, ask in a concise message. Key each answer to its DIM/view
or requirement entry and record the user's words. Do not invent tool names or
interpret a timeout as consent. Existing explicit authorization still applies;
ask only for requirements that remain unresolved.

<!-- skill:endif -->

Gate: the ask round returned answers, consent is recorded in the ledger,
`report_A.md` and `REQUIREMENTS.md` exist. Entering Role 2 without this
gate is the cardinal violation.

**Unattended:** the gate is a self-review. Re-read `report_A.md` and `REQUIREMENTS.md` against the sheet, write one
paragraph of decision with the open risks, and go on only when every required field is filled (a recorded assumption
fills a field; an empty one does not). Entering Role 2 without it is still the cardinal violation.
