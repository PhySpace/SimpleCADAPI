# Single-Part Modeling: verifier contract patterns and image review

**Read when:** Role 3 selects the checks for a stage.

## Verifier contract patterns

Role 3 selects the applicable checks per stage; it does not mechanically run
every pattern. A contract may combine:

- dimensional measurements with explicit tolerance bounds;
- topology, axis, and face-location queries for required features;
- BREP closure, positive volume, and solid-count checks;
- swept insertion envelopes for screws, tools, or assembly access, with a
  zero-collision criterion;
- clearance and interference checks against already-built substructures;
- demolding or tool-direction access checks when manufacturing intent requires;
- named renders and isolated per-region visual verdicts;
- functional motion or clearance checks when the part has moving interfaces;
- FEM only when service conditions are stated in `REQUIREMENTS.md`.

Every selected pattern needs a deterministic pass/fail condition and a
known-bad hypothesis proof before the current stage is modeled.

**Unattended:** the isolated-review bindings below that name the user as reviewer do not apply. Use the replacement in
`discipline/operating-modes.md`: a fresh-context check of your own against the written visual contract, using a
subagent if the host offers one, quoting the observation per region; if no independent context is possible the visual gate
still closes on the written observations, and the report says the review was not independent. A mismatch is never overridden.

<!-- skill:if omp -->

### Host binding: mandatory isolated image review (omp)

When Role 3 selects visual verification, any image-based acceptance judgment
must be executed by a clean-context reviewer. The context that produced a
render cannot certify it. Role 3 defines the visual contract before Role 4
builds: reference/render paths, named views, regions, required verdict fields,
and the reviewer input description.

- Default: spawn one isolated `task` reviewer with file paths and the written
  shape description from `REQUIREMENTS.md`; demand structured per-region
  `match` / `mismatch` / `unreviewable` verdicts with reasons.
- If a standing reviewer peer exists, use `hub` to send the same contract and
  record its reply verbatim.
- A mismatch cannot be overridden by the main context. Repair the owning
  model, render again, and repeat the isolated review.
- If neither reviewer mechanism exists, the visual gate remains open and the
  stage cannot pass.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: mandatory isolated image review (opencode)

When Role 3 selects visual verification, any image-based acceptance judgment
must be executed by a subagent with a clean context. The context that
produced a render cannot certify it. Role 3 defines the visual contract
before Role 4 builds: reference/render paths, named views, regions, required
verdict fields, and the reviewer input description.

- Default and only mechanism: spawn one isolated reviewer with the `task`
  tool, `subagent_type: "general"` (fresh context, able to read image
  files). Pass the render/reference file paths and the written shape
  description from `REQUIREMENTS.md`; require structured per-region `match`
  / `mismatch` / `unreviewable` verdicts with reasons in the reviewer's
  final report, and quote that report verbatim in the stage evidence. Spawn
  a fresh reviewer for every re-review; do not resume a previous reviewer
  session (task-id reuse would carry the context of the earlier render it
  already judged).
- opencode has no standing-reviewer-peer mechanism; the hub option cannot
  be mapped. If the `task` tool is unavailable, the visual gate remains
  open and the stage cannot pass.
- A mismatch cannot be overridden by the main context. Repair the owning
  model, render again, and repeat the isolated review.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode -->

### Host binding: mandatory isolated image review (Claude Code / ZCode)

When Role 3 selects visual verification, any image-based acceptance judgment
must be executed by a subagent with a clean context. The context that
produced a render cannot certify it. Role 3 defines the visual contract
before Role 4 builds: reference/render paths, named views, regions, required
verdict fields, and the reviewer input description.

- Default and only mechanism: spawn one isolated reviewer subagent (ZCode
  `Agent` tool / Claude Code `Task` tool, `subagent_type: "general-purpose"`
  — fresh context, able to read image files). Pass the render/reference file
  paths and the written shape description from `REQUIREMENTS.md`; require
  structured per-region `match` / `mismatch` / `unreviewable` verdicts with
  reasons in the reviewer's final report, and quote that report verbatim in
  the stage evidence. The subagent's final message is the review record.
- Spawn a fresh reviewer for every re-review; do not resume a previous
  reviewer session or reuse a task id (its context carries the earlier
  render it already judged, so it can no longer certify a new one).
- This host has no standing-reviewer-peer mechanism; the hub option cannot
  be mapped. If the subagent spawn tool is unavailable, the visual gate
  remains open and the stage cannot pass.
- A mismatch cannot be overridden by the main context. Repair the owning
  model, render again, and repeat the isolated review.

<!-- skill:endif -->

<!-- skill:if codex -->

### Host binding: mandatory isolated image review (codex)

When Role 3 selects visual verification, any image-based acceptance judgment
must come from a context that did not produce the render; the modeling
context cannot certify it. Role 3 defines the visual contract before Role 4
builds: reference/render paths, named views, regions, required verdict
fields, and the reviewer input description.

- codex has no subagent spawn mechanism. The fallback reviewer is the user:
  present the render together with the written visual contract (views,
  regions, and the verdict fields you need) in one message, then stop and
  wait. Record the user's verdict verbatim in the stage evidence as the
  review record; a partial verdict is `unreviewable` for the uncovered
  regions.
- If the user cannot review in this round, the visual gate remains open and
  the stage cannot pass; do not substitute the modeling context's own
  judgment for the review.
- A mismatch cannot be overridden by the modeling context. Repair the owning
  model, render again, and repeat the review.

<!-- skill:endif -->

<!-- skill:if dsh,kimicode -->

### Host binding: mandatory isolated image review, conservative fallback (dsh / kimicode)

When Role 3 selects visual verification, any image-based acceptance judgment
must come from a context that did not produce the render; the modeling
context cannot certify it. Role 3 defines the visual contract before Role 4
builds: reference/render paths, named views, regions, required verdict
fields, and the reviewer input description.

- No subagent mechanism is assumed for this host. If the host provides one,
  spawn an isolated reviewer subagent with fresh context per re-review, pass
  the render/reference paths and the written shape description, require
  structured per-region `match` / `mismatch` / `unreviewable` verdicts with
  reasons, and quote its report verbatim in the stage evidence.
- Without a subagent mechanism, the fallback reviewer is the user: present
  the render together with the written visual contract in one message, then
  stop and wait; record the user's verdict verbatim as the review record. If
  the user cannot review in this round, the visual gate remains open and the
  stage cannot pass.
- A mismatch cannot be overridden by the modeling context. Repair the owning
  model, render again, and repeat the review.

<!-- skill:endif -->
