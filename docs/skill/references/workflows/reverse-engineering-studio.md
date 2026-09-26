# Workflow: Reverse-Engineering Studio (human-in-the-loop)

Drive the interactive reconstruction studio (the standalone [sca-web-editor](https://github.com/PhySpace/sca-web-editor) re-mode) as the agent
side of a two-actor loop: a human annotates the STEP target in the browser,
the agent reconstructs from those annotations, and the browser displays the
artifacts for the next refinement round.

## Goal and scope

Use when a human operator is available to supply feature intent for a STEP
target — the variable that pure LLM+inspection reconstruction cannot recover
from geometry alone. The human picks entities, draws regions, tags operation
tips, and writes free text; the agent turns each submission into FTC code and
verification artifacts. Without an operator, stay on the autonomous path
(`step-reconstruction.md`).

## Hard rules

- **Only the human's browser writes `re_work/submission.json`.** The agent
  must never POST `/api/submit` or author the submission file; the submission
  is the ground-truth human signal and the training record depends on it being
  genuine.
- The agent writes artifacts; it does not edit geometry in the UI. The UI has
  no geometry-editing surface — code is the single source of truth.
- **Artifact scripts are self-contained.** Any transcription — including
  contours and fitted curves — must end up as parameter literals inside the
  rebuild script; it must not read the target STEP, sidecars, or generated
  blocks at rebuild time. One-shot extraction harnesses live beside the case
  (e.g. `re_work/extract_*.py`) and their output is pasted in as literals.
- Verification stays external to the modeling scripts (same rule as
  everywhere else): run verifiers, comparison renders, and evaluation reports
  as separate steps.

## Session layout

```text
<case_dir>/
  target.step
  re_work/
    annotations.jsonl    # append-only annotation events (UI authoritative)
    submission.json      # atomic handoff: annotations + server-side context
    submission.seq
    session.ndjson       # full event recording (selections, resolves, submits,
                         # artifact versions) — the training-data side channel
    snapshots/snap-N.png # viewport snapshot submitted with round N
    extract_*.py         # agent one-shot extraction harnesses (optional)
    rebuild.py           # agent artifact: FTC reconstruction source (self-contained)
    rebuilt.step
    rebuilt.scadpkg      # captured v3 product package (loads in the UI)
    comparison.png       # render_step_comparison_rpath shared-camera diff
    evaluation.json      # external verification report (verdict + named gaps)
```

`submission.json` carries:

- per annotation: the free-form `text` (chips serialize inline as
  `[face:12](face:12)` / `[fillet](op:fillet)`), `entity_ids` (canonical ids
  like `face:12`), `operations` (referenced operation tip ids), the screen
  polygon, and a server-composed context card per entity
  (`describe_entity` geometry, bounds, capped adjacency). Unresolvable ids
  are listed in `unresolved_entity_ids` — treat them as data errors, never
  silently dropped input.
- `operation_context`: the full tip for every referenced operation (see
  below), so the agent receives the doc pointers without scraping.
- the round `note` and the viewport `snapshot`.

## The studio UI (what the operator does)

- **Select / draw** (left viewport): face/edge/vertex/body picking with
  persistent highlight; circle and lasso drawing resolve a screen region to
  entity ids server-side.
- **Free-form composer**: picked entities land in the text input as inline
  atomic chips (color-coded face/edge/vertex/body), peers of plain text. The
  operation palette above it lists five categories — **sketch** (constrained
  profiles), **solid build** (extrude/revolve/sweep/loft/booleans),
  **modify** (fillet/chamfer), **surface** (patch/fill/gordon/ruled),
  **pattern** (linear/radial) — and each button inserts an operation chip.
  Tagging an operation next to entity tags declares *what the agent should
  read* for those entities. Enter commits an annotation (IME-safe: candidate
  confirmation never submits), Shift+Enter inserts a newline, the chip row
  shows committed annotations per round.
- **Right side**: the rebuilt viewport (loads the agent's v3 package), the
  shared-camera comparison image, and tabs for the highlighted rebuild source
  (feature rows reveal their source lines), the feature DAG tree, the
  evaluation report, the last submission, and a context preview showing
  exactly what the agent will see (minus server-added entity context).
- **SUBMIT** hands the round to the waiting agent; the UI then polls artifact
  versions and refreshes automatically.

## Operation tips (content is markdown, not code)

Each palette entry is a packaged prompt defined by
`sca_web_editor/operations/<op_id>.md` in the sca-web-editor repo: YAML-style frontmatter (`label`,
`category`, `api`, `reads`, `doc_refs`) plus the hint text as body. The
registry loader validates and serves them (`GET /api/operations`) and
`compose_submission` embeds the tips for every referenced operation.

- Tuning or adding a tip is a markdown edit — no frontend or code change;
  file edits are picked up via mtime without a server restart.
- `reads` declares which geometric features of the tagged entities the
  operation consumes (context assembly guidance); `doc_refs` are
  repo-relative skill references the agent should read first; the body is the
  imperative usage note.
- Malformed files are named in the payload `errors` list and logged — the
  registry never silently drops a broken file.

## Agent loop

1. Start the studio and hand the URL to the operator (all commands run from a
   checkout of [sca-web-editor](https://github.com/PhySpace/sca-web-editor)):

   ```bash
   uv run python -m sca_web_editor <case_dir> --daemon
   ```

   The detached server binds `127.0.0.1:7170` and opens
   `http://127.0.0.1:7170/`, the single Web Editor entry. Choose `Re-mode`
   in the mode switcher. During development run `npm run dev` in the
   sca-web-editor repo, which proxies `/api` and `/rpc`.

2. Block on the next submission (stay under the Bash tool timeout):

   ```bash
   uv run python -m sca_web_editor <case_dir> --wait-only --timeout 590
   ```

   Exit 0 = fresh submission; 124 = timeout (re-check `re_work/submission.json`
   once before falling back to chat); 1 = server died (restart with
   `--daemon`, the browser tab reconnects).

3. Read `re_work/submission.json`. Annotations are intent hints, not geometry
   truth — an `exact_copy`-style region still needs measured parameters or
   literal transcription. The per-entity context cards carry measured
   geometry (radii, lengths, centers); anything beyond them comes from the
   inspection API in a separate harness, never from inside the rebuild
   script.

4. Reconstruct per the reconstruction contract: FTC feature blocks per
   `discipline/feature-tree-convention.md`, blends as boolean-seam fillets
   via `ql-playbook.md` Pattern B selectors re-resolved immediately after
   the producing union. Two kernel-ordering facts that keep the tree
   buildable:

   - Cut through-bores **before** blend fillets — a filleted body can reject
     later boolean cuts in OCC. Bore each ring into a tube first, then union
     the transcribed body, then blend.
   - Curved freeform contours go through the geometry transcription tier —
     sample, `fit_cubic_bspline_control_points`, then pass the fitted
     literals to `make_spline_redge` / `make_three_point_arc_redge` /
     `make_segment_redge` (the fitter's `to_dict()` returns
     `unique_knots` paired with `multiplicities`; the full `knots` vector is
     not the edge-constructor contract).

5. Write the artifact set into `re_work/` (names are fixed — the UI polls
   them): `rebuild.py` (self-contained), `rebuilt.step`,
   `rebuilt.scadpkg` (via `scad.capture`), `comparison.png` (via
   `render_step_comparison_rpath`), `evaluation.json` (verdict plus named
   gaps — an approximation stop must say what is unrecovered).

6. Loop to step 2 for the next refinement round. Finish with:

   ```bash
   uv run python -m sca_web_editor <case_dir> --shutdown
   ```

## Data output

`re_work/session.ndjson` is the training record: every selection, region
resolve, annotation event, operation-chip insert, submission, and artifact
version, with timestamps. Keep it alongside the artifact set when harvesting
cases; it is the trajectory, not just the endpoint pair.
