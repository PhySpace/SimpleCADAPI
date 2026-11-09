# Single-Part Modeling: Role 3 host bindings

**Read when:** Role 3 starts a stage (the hypothesis loop and the TODO state machine for the Verifier Planner).

<!-- skill:if omp -->

### Host binding: persistent REPL and TODO state machine for Verifier Planner (omp)

Use the persistent `eval` tool (language `py`) for hypothesis snippets and
known-bad probes. Keep setup, hypothesis, and final check cells incremental;
do not hide an unproven check in a temporary one-shot script. Use `todo` to
make the current stage's verification contract a real gate, not a note.

Role 2 creates the stable stage tasks in the `Build & Verify` phase. For each
stage, the initial task order is:

```text
S1 plan verifier
S1 model
S1 run verifier
S2 plan verifier
S2 model
S2 run verifier
...
```

Use the exact task strings consistently. When Role 3 enters a stage, start its
`plan verifier` task:

```text
todo(op="start", task="S1 plan verifier")
```

If a stage was added after the original initialization, append all three tasks
as one ordered batch before starting the first one:

```text
todo(op="append", phase="Build & Verify", items=[
  "S3 plan verifier",
  "S3 model",
  "S3 run verifier",
])
todo(op="start", task="S3 plan verifier")
```

Do not append a later stage's tasks while the current stage is still open. A
repair item for the current stage is the exception: append it next to the
owning task and keep the stage open.

After the verifier contract, executable check, hypothesis evidence, and
known-bad proof are recorded in `BUILD_PLAN.md`, close the planning gate and
open the modeling gate in the same work turn:

```text
todo(op="done", task="S1 plan verifier")
todo(op="start", task="S1 model")
```

Role 4 owns the model task. It must not start before the `plan verifier` task
is done. After Role 4's source run completes, Role 4 closes `S1 model` and
starts `S1 run verifier`; Role 3 then executes the exact prepared function or
script named in that task.

On a passing verification, record the output/evidence and close the gate:

```text
todo(op="done", task="S1 run verifier")
```

Only then may Role 3 start `S2 plan verifier`. On a failed check, do not call
`done`, `drop`, or rewrite the acceptance criterion merely to clear the list.
Identify the owner and append a stable repair task in the same phase, for
example:

```text
todo(op="append", phase="Build & Verify", items=[
  "repair: S1 verifier collision check",
])
todo(op="start", task="repair: S1 verifier collision check")
```

If the check is wrong, repair and re-prove the verifier contract; if the model
is wrong, keep the verifier task intact and append a model repair item. After
repair, return to the current stage's `run verifier`; never advance to `S2`.
Use `todo(op="view")` after a repair or interruption to re-ground task text
and status. Batch TODO calls with the real REPL, file, or verification work in
the same turn; keep task strings stable and mark each item done immediately at
its actual gate.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: file-based hypothesis loop and TODO state machine for Verifier Planner (opencode)

opencode has no persistent REPL. Python runs through the `bash` tool and
every invocation is a fresh process: names do not survive between calls.
Keep each hypothesis snippet, known-bad probe, and final check as a numbered
script file under the part directory (e.g.
`<part-dir>/verify/s1_hypothesis.py`, `s1_known_bad.py`, `s1_verify.py`)
and run it with `python` via `bash`; persist intermediate state in files
(JSON, pickle, or a captured package) and reload it in the next script. The
script file is the evidence: do not hide an unproven check in a throwaway
one-shot command whose text is lost. Use `todowrite` to make the current
stage's verification contract a real gate, not a note.

Role 2 creates the stable stage tasks in the `Build & Verify` phase. For
each stage, the initial task order is:

```text
S1 plan verifier
S1 model
S1 run verifier
S2 plan verifier
S2 model
S2 run verifier
...
```

Use the exact task strings as `content` values in every `todowrite` call.
When Role 3 enters a stage, submit the full list with that item as the only
`in_progress` entry. If a stage is added after the original initialization,
add its three tasks as one ordered batch in the next rewrite before starting
the first one; do not add a later stage's tasks while the current stage is
still open. A repair item for the current stage is the exception: add it
next to the owning task and keep the stage open.

After the verifier contract, executable check, hypothesis evidence, and
known-bad proof are recorded in `BUILD_PLAN.md`, close the planning gate and
open the modeling gate in one rewrite: `S1 plan verifier` -> `completed`,
`S1 model` -> `in_progress`. Role 4 owns the model task; it must not be
`in_progress` while `S1 plan verifier` is unfinished. After Role 4's source
run completes, mark `S1 model` completed, set `S1 run verifier`
`in_progress`, and execute the exact prepared script named in that task.

On a passing verification, record the output/evidence and mark `S1 run
verifier` completed; only then may `S2 plan verifier` become `in_progress`.
On a failed check, do not flip statuses merely to clear the list: identify
the owner, add a stable `repair:` item (e.g. `repair: S1 verifier collision
check`), make it the `in_progress` item, and after the repair return to the
current stage's `run verifier`; never advance to `S2`. The `todowrite`
result echoes the current list — use it to re-ground task strings and status
after a repair or an interruption. Batch each rewrite with the real bash,
file, or verification work in the same turn.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode -->

### Host binding: file-based hypothesis loop and TODO state machine for Verifier Planner (Claude Code / ZCode)

This host has no persistent REPL. Python runs through the `Bash` tool and
every invocation is a fresh process: names do not survive between calls.
Keep each hypothesis snippet, known-bad probe, and final check as a numbered
script file under the part directory (e.g.
`<part-dir>/verify/s1_hypothesis.py`, `s1_known_bad.py`, `s1_verify.py`) and
run it with `python` via `Bash`; persist intermediate state in files (JSON,
pickle, or a captured package) and reload it in the next script. The script
file is the evidence: do not hide an unproven check in a throwaway one-shot
command whose text is lost. Use `TodoWrite` to make the current stage's
verification contract a real gate, not a note.

Role 2 creates the stable stage tasks in the `Build & Verify` phase. For each
stage, the initial task order is:

```text
S1 plan verifier
S1 model
S1 run verifier
S2 plan verifier
S2 model
S2 run verifier
...
```

Use the exact task strings as `content` values in every `TodoWrite` call.
When Role 3 enters a stage, submit the full list with that item as the only
`in_progress` entry. If a stage is added after the original initialization,
add its three tasks as one ordered batch in the next rewrite before starting
the first one; do not add a later stage's tasks while the current stage is
still open. A `repair:` item for the current stage is the exception: add it
next to the owning task and keep the stage open.

After the verifier contract, executable check, hypothesis evidence, and
known-bad proof are recorded in `BUILD_PLAN.md`, close the planning gate and
open the modeling gate in one rewrite: `S1 plan verifier` -> `completed`,
`S1 model` -> `in_progress`. Role 4 owns the model task; it must not be
`in_progress` while `S1 plan verifier` is unfinished. After Role 4's source
run completes, mark `S1 model` completed, set `S1 run verifier`
`in_progress`, and execute the exact prepared script named in that task.

On a passing verification, record the output/evidence and mark `S1 run
verifier` completed; only then may `S2 plan verifier` become `in_progress`.
On a failed check, do not flip statuses merely to clear the list: identify
the owner, add a stable `repair:` item (e.g. `repair: S1 verifier collision
check`), make it the `in_progress` item, and after the repair return to the
current stage's `run verifier`; never advance to `S2`. The `TodoWrite` result
echoes the current list — use it to re-ground task strings and status after a
repair or an interruption. Batch each rewrite with the real `Bash`, file, or
verification work in the same turn.

<!-- skill:endif -->

<!-- skill:if codex -->

### Host binding: file-based hypothesis loop and plan state machine for Verifier Planner (codex)

codex has no persistent REPL. Python runs through the shell tool and every
invocation is a fresh process: names do not survive between calls. Keep each
hypothesis snippet, known-bad probe, and final check as a numbered script
file under the part directory (e.g. `<part-dir>/verify/s1_hypothesis.py`,
`s1_known_bad.py`, `s1_verify.py`), run it with `python` through the shell,
and persist intermediate state in files (JSON, pickle, or a captured package)
reloaded by the next script. The script file is the evidence: do not hide an
unproven check in a throwaway one-shot command whose text is lost. Use
`update_plan` to make the current stage's verification contract a real gate,
not a note.

Role 2 creates the stable stage steps in the `Build & Verify` phase in the
order `S1 plan verifier`, `S1 model`, `S1 run verifier`, then `S2 ...`, and
so on. Use the exact step strings in every `update_plan` call. When Role 3
enters a stage, submit the full plan with that step as the only `in_progress`
entry. If a stage is added after the original initialization, add its three
steps as one ordered batch in the next rewrite before starting the first one;
do not add a later stage's steps while the current stage is still open. A
`repair:` step for the current stage is the exception: add it next to the
owning step and keep the stage open.

After the verifier contract, executable check, hypothesis evidence, and
known-bad proof are recorded in `BUILD_PLAN.md`, close the planning gate and
open the modeling gate in one rewrite: `S1 plan verifier` -> `completed`,
`S1 model` -> `in_progress`. Role 4 owns the model step; it must not be
`in_progress` while `S1 plan verifier` is unfinished. After Role 4's source
run completes, mark `S1 model` completed, set `S1 run verifier`
`in_progress`, and execute the exact prepared script named in that step.

On a passing verification, record the output/evidence and mark `S1 run
verifier` completed; only then may `S2 plan verifier` become `in_progress`.
On a failed check, do not flip statuses merely to clear the list: identify
the owner, add a stable `repair:` step, make it the `in_progress` step, and
after the repair return to the current stage's `run verifier`; never advance
to `S2`. Batch each rewrite with the real shell, file, or verification work
in the same turn.

<!-- skill:endif -->

<!-- skill:if dsh,kimicode -->

### Host binding: file-based hypothesis loop and checklist state machine for Verifier Planner (dsh / kimicode)

No persistent REPL or native TODO tool is assumed for this host. Python runs
through the shell and every invocation is a fresh process: names do not
survive between calls. Keep each hypothesis snippet, known-bad probe, and
final check as a numbered script file under the part directory (e.g.
`<part-dir>/verify/s1_hypothesis.py`, `s1_known_bad.py`, `s1_verify.py`),
run it with `python` through the shell, and persist intermediate state in
files (JSON, pickle, or a captured package) reloaded by the next script. The
script file is the evidence: do not hide an unproven check in a throwaway
one-shot command whose text is lost.

Keep the stage checklist (`S1 plan verifier`, `S1 model`, `S1 run verifier`,
then `S2 ...`) as a fenced checklist section in `BUILD_PLAN.md` and treat it
as the gate ledger: when Role 3 enters a stage, mark that stage's
`plan verifier` item in-progress in the same turn; when the verifier
contract, executable check, hypothesis evidence, and known-bad proof are
recorded, mark `S1 plan verifier` done and `S1 model` in-progress in one
edit. Role 4 owns the model item and must not start while `S1 plan verifier`
is unfinished. After Role 4's source run completes, mark `S1 model` done, set
`S1 run verifier` in-progress, and execute the exact prepared script named in
that item. On a passing verification, record the output/evidence and mark
`S1 run verifier` done; only then may `S2 plan verifier` start. On a failed
check, do not edit statuses merely to clear the list: identify the owner, add
a stable `repair:` item next to the owning item, and after the repair return
to the current stage's `run verifier`; never advance to `S2`. Quote the
current checklist state when reporting a gate decision. Batch each checklist
edit with the real shell, file, or verification work in the same turn.

<!-- skill:endif -->
