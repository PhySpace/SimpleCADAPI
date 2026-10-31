# Single-Part Modeling: Role 2, Master Planner

Outline: `workflows/single-part-modeling.md`.

## Role 2 — Master Planner

From `REQUIREMENTS.md` only — no API detail, no step-level modeling.

1. Choose the construction strategy (profile-driven vs block-and-feature)
   and fix the datum from the functional interface; one-paragraph rationale
   each.
2. Design the construction as numbered stages `S1..Sn`. For each stage state
   exactly what new substructure is complete at its output boundary and what
   later stages are not yet included. Pair every stage with its future
   verification target, but leave the executable verification design to Role
   3.
3. Write `BUILD_PLAN.md` with the stage output boundaries, datum, intended
   construction strategy, and the requirement-to-stage mapping. Role 3 adds
   verification contracts and Role 4 adds modeling hypotheses and source
   details while the loop runs.
4. Initialize the TODO tool with phases `Requirements / Plan / Build & Verify /
   Export`. For each stage create stable `plan verifier`, `model`, and `run
   verifier` items. The `run verifier` item is completed only after Role 3 has
   executed the prepared check against the Role 4 result. Mark Requirements
   done, Plan done, and start the first stage's `plan verifier` item.

Present the plan in ≤10 lines. No approval gate; enter the Role 3/4 loop.

**Unattended:** the plan is not presented to anyone; it is the file `BUILD_PLAN.md` and a short summary in the report
(`discipline/operating-modes.md`). Where the plan has two viable construction strategies, take the one that meets the
stated requirements and is easier to change later, and record the other in `BUILD_PLAN.md`.

<!-- skill:if omp -->

### Host binding: TODO tool (omp)

Tool name: `todo`. Operations: `init(list=[{phase, items[]}])`,
`start(task)`, `done(task|phase)`, `drop(task|phase)`, `block(task, reason)`,
`unblock(task)`, `append(phase, items[])`, `rm`, `view`. Contract: batch
`todo` calls together with real work in the same turn; task strings are stable
identifiers — quote them exactly when completing. Keep the current stage's
`model` item pending until its `plan verifier` artifact exists. A failed
`run verifier` reopens the owning verifier or model through a `repair:` item;
never advance the stage while either owner is open.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: TODO tool (opencode)

Tool name: `todowrite`. There is a single operation: submit the whole list
as `todos=[{content, status, priority}]` with statuses
`pending / in_progress / completed / cancelled`. Every call rewrites the
full list, so start, done, drop, and append are all expressed by including
every current item with its updated status in the next call. Contract: batch
the rewrite with real work in the same turn; `content` strings are the
stable identifiers — quote them exactly when completing (`S1 plan
verifier`, `repair: S1 verifier collision check`); keep exactly one item
`in_progress` at a time; mark an item `completed` only at its actual gate,
never speculatively. There is no `blocked` status: a blocked item stays
`in_progress` and a follow-up item records the blocker. Keep the current
stage's `model` item pending until its `plan verifier` artifact exists. A
failed `run verifier` reopens the owning verifier or model through a
`repair:` item; never advance the stage while either owner is open.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode -->

### Host binding: TODO tool (Claude Code / ZCode)

Tool name: `TodoWrite`. There is a single operation: submit the whole list as
`todos=[{content, status, priority}]` with statuses
`pending / in_progress / completed` and priorities `high / medium / low`.
Every call replaces the full list, so start, done, drop, and append are all
expressed by including every current item with its updated status in the next
call. Contract: batch the rewrite with real work in the same turn; `content`
strings are the stable identifiers — quote them exactly when completing
(`S1 plan verifier`, `repair: S1 verifier collision check`); keep exactly one
item `in_progress` at a time; mark an item `completed` only at its actual
gate, never speculatively. There is no `blocked` status: a blocked item stays
`pending` or `in_progress` and a follow-up `repair:` item records the
blocker. Keep the current stage's `model` item pending until its
`plan verifier` artifact exists. A failed `run verifier` reopens the owning
verifier or model through a `repair:` item; never advance the stage while
either owner is open.

<!-- skill:endif -->

<!-- skill:if codex -->

### Host binding: TODO tool (codex)

Tool name: `update_plan`. One operation: submit the whole plan as
`plan=[{step, status}]` with statuses `pending / in_progress / completed`.
Every call rewrites the full plan, so start, done, drop, and append are all
expressed by including every current step with its updated status in the next
call. Contract: batch the rewrite with real work in the same turn; `step`
strings are the stable identifiers — quote them exactly (`S1 plan verifier`,
`repair: S1 verifier collision check`); keep exactly one step `in_progress`
at a time; mark a step `completed` only at its actual gate, never
speculatively. There is no `blocked` status: a blocked step stays `pending`
or `in_progress` and a follow-up `repair:` step records the blocker. Keep the
current stage's `model` step pending until its `plan verifier` artifact
exists. A failed `run verifier` reopens the owning verifier or model through
a `repair:` step; never advance the stage while either owner is open. If
`update_plan` is unavailable in the current session, keep the same list as a
checklist section in `BUILD_PLAN.md`, update it in the same turn as the work
it gates, and quote the current checklist state when reporting a gate
decision.

<!-- skill:endif -->

<!-- skill:if dsh,kimicode -->

### Host binding: TODO tool, conservative fallback (dsh / kimicode)

No native TODO tool is assumed for this host. Keep the stage checklist as a
fenced checklist section in `BUILD_PLAN.md` and treat the file as the gate
ledger: update it in the same turn as the work it gates; quote the exact item
strings (`S1 plan verifier`, `repair: S1 verifier collision check`); keep
exactly one item marked in-progress; mark an item done only at its actual
gate, never speculatively; record blockers as `repair:` items instead of a
blocked status. Keep the current stage's `model` item pending until its
`plan verifier` artifact exists. A failed `run verifier` reopens the owning
verifier or model through a `repair:` item; never advance the stage while
either owner is open. When claiming a gate decision, quote the current
checklist state. If this host does provide a native TODO tool, map this block
onto it and keep the same gate semantics.

<!-- skill:endif -->
