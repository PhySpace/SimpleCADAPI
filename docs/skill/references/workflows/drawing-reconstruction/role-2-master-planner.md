# Drawing Reconstruction: Role 2, Master Planner

Part of `workflows/drawing-reconstruction.md`. Load when Role 2 starts.

## Role 2 — Master Planner

From `report_A.md` and `REQUIREMENTS.md` only — no API detail, no
step-level modeling.

1. **Feature inference.** Build the feature hypothesis list: one entry per
   inferred feature (base body, segments, bores, groove lattices, bosses,
   lugs, modifiers), each citing its evidence (`DIM-xxx` ids, view-list
   entries, 〔归属〕 conclusions) and carrying a confidence mark. Check
   `scad.std.gear` / `scad.std.bearing` before hand-modeling anything
   standard-like. Function/purpose narrative stays here and in the user
   conversation — it never re-enters the parse report.
2. **Stage plan.** Design the construction as `S1..Sn`: base body first,
   then major segments, feature groups as their own late stages (pattern
   lattices after their prototype feature is proven), modifiers last. Pair
   every stage with the DIM-id subset it must satisfy.
3. Write `BUILD_PLAN.md`: stage output boundaries, datum story, DIM-id
   mapping, hypothesis list. Role 3 appends verification contracts; Role 4
   appends modeling hypotheses while the loop runs.
4. Initialize the TODO tool with phases `Requirements / Plan / Build &
   Verify / Roundtrip / Export`; per stage create `plan verifier`, `model`,
   `run verifier` items; create the roundtrip tasks
   (`roundtrip: generate sheet`, `roundtrip: parse report B`,
   `roundtrip: diff and triage`). Mark Requirements and Plan done; start
   the first stage's `plan verifier`.

Present the plan in ≤10 lines. No approval gate; enter the Role 3/4 loop.

<!-- skill:if omp -->

### Host binding: TODO tool (omp)

Tool `todo`: `init(list=[{phase, items[]}])`, `start(task)`, `done(task)`,
`append(phase, items[])`, `view`. Task strings are stable identifiers —
quote them exactly. Keep the stage's `model` item pending until its
`plan verifier` artifact exists; a failed `run verifier` opens a
`repair:` item for the owner; never advance while an owner is open. Batch
`todo` calls with real work in the same turn.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: TODO tool (opencode)

Tool `todowrite`: submit the whole list every call as
`todos=[{content, status, priority}]` with statuses
`pending / in_progress / completed / cancelled`. `content` strings are the
stable identifiers — quote them exactly (`S1 plan verifier`,
`repair: S1 verifier bore depth`, `roundtrip: diff and triage`). Exactly one
item `in_progress` at a time; mark `completed` only at the real gate; a
blocked item stays `in_progress` with a follow-up item recording the
blocker. Keep the stage's `model` pending until its `plan verifier`
artifact exists; a failed `run verifier` opens a `repair:` item for the
owner.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode,codex,dsh,kimicode -->

### Host binding: plan and checklist state

Use the host's available plan/TODO tool. If none exists, maintain the same stage
checklist in `BUILD_PLAN.md`, updating the artifact after each real result.
Keep `plan verifier`, `model`, `run verifier` and any `repair:` items distinct;
complete them only when the corresponding evidence exists.

<!-- skill:endif -->
