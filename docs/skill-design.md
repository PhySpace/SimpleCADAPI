# The skill: design contract

`docs/skill/` is the skill an agent loads to use SimpleCADAPI. This file is the contract its pages follow. The rules here
are checked by `python tools/skillbuild.py --check` (see "Checks"), so a page that breaks one fails the build.

## What the skill optimises for

1. **Few agent turns.** An agent reads what a step needs in **one parallel batch** and then works. Pages are small and
   have one job so they can be loaded separately, and the router tells the agent which pages belong together.
2. **A small reading budget.** The first batch of any route is at most **1,200 compiled lines** (router, the two
   always-read pages, the workflow page and its `Read now` files); every later batch stays under the same bound. (Measured before this design: a median of 1,493 lines and 7 files read before the first write, p90 2,501
   lines and 20 files.)
3. **One home for each rule.** A rule is stated once, with its reason; other pages link to it.
4. **Two modes.** Every workflow runs interactive or unattended (`references/discipline/operating-modes.md`).
5. **Four curated targets.** The skill compiles to seven harness targets; `zcode`, `opencode`, `claudecode` and `codex` are
   written for. `omp`, `dsh` and `kimicode` are compiled from the same sources and must pass the checks, with generic wording.

## The layers

```text
SKILL.md                      router: start here, route table with read sets, always-on rules (<= 130 lines)
references/workflows/         one lifecycle per task; each has Read now / Read when / Unattended mode
references/workflows/<name>/  the role or stage pages of a long workflow, loaded when the role starts
references/domains/           capabilities (what the SDK offers for a kind of task)
references/discipline/        reasoning, invariants, rules (core-rules, operating-modes, the notebook rules ...)
references/docs/guides/       how the runtime works
references/docs/api|stdlib|core/   generated signatures (never hand-edited)
```

## Page contracts

**Every hand-written page** (everything but `docs/api`, `docs/stdlib`, `docs/core`) is at most **300 lines** (`SKILL.md`
at most **130**). A longer page is split by job, not trimmed. The one exception is a versioned run contract (its first lines
say `Contract ID:`), which an external harness reads whole.

**Domain and discipline pages** open, within their first 8 lines, with `**Read when:** <the trigger>.` Nothing else is
required of their body.

**Workflow pages** (`references/workflows/*.md`) have these sections, with exactly these headings:

```markdown
## Read now (one parallel batch)
| File | Why |
| --- | --- |
| `domains/requirement-refinement.md` | ... |

## Read when
| When | File |
| --- | --- |
| a Role starts | `workflows/<name>/role-1-....md` |

## Unattended mode
| Interactive gate | Unattended replacement |
| --- | --- |
| Role 1 consent gate | ... |
```

- `Read now` lists every file the first batch needs besides the always-read pages, **including the workflow's own role-1/first-stage page**; paths are
  written relative to `references/` (for example `domains/part-modeling.md`) and in backticks, one per table row.
- `Read when` lists everything else with its trigger; nothing is read "just in case".
- `Unattended mode` has one row for **every** place the workflow asks a person, waits for one, or needs a second reviewer
  (search the old text for `⛔`, "ask", "user", "consent", "confirm", "question", "review"), using the replacements in
  `discipline/operating-modes.md`. A workflow with no such place says so in one sentence.
- `core-rules.md` and `operating-modes.md` are read on every route (the router says so), so `Read now` does not list them.
- The compiled lines of `SKILL.md` + `core-rules.md` + `operating-modes.md` + the workflow page + its `Read now` files are at
  most **1,200** (checked per target; the lint prints the sizes with `--read-budget`).

**The router's route table** repeats the workflow page plus its `Read now` set in its own column, so an agent can issue the batch
straight from the table without opening the workflow first. The two must agree (checked).

## Parallel reading

The router tells the agent to read a batch in one go. How is per target (compile blocks in `SKILL.md`):

- `claudecode`, `zcode`: all `Read` calls of the batch in one message.
- `opencode`: all `read` calls of the batch in one response.
- `codex`: one shell command that prints the batch: `cd <skill dir> && tail -n +1 a.md b.md c.md` (each file is preceded by a
  `==> name <==` header).
- `omp`, `dsh`, `kimicode`: the generic sentence ("request the whole batch together if your tools allow it").

Pages that name API pages for a step list them as one batch too (`Read now` / a `Read when` row), never "read as needed".

## Splitting and merging rules (no loss)

- **Move, do not rewrite.** When a long page is split, each rule, table row, example, checklist item and `skill:if` block
  survives in exactly one new page (or is deleted as a verbatim duplicate of text kept elsewhere, and the report says
  where). Changing meaning is a separate, labelled edit.
- The old page's name stays as the outline (workflow or guide) so links keep working; the outline links to the new pages.
- Stable file names are in the file map below. Cross-links between owners only use the names listed there.

## File map

Names in **bold** are new.

```text
SKILL.md
references/README.md                      generated tables + this layering
references/SDK_OVERVIEW.md, ql-playbook.md, scadpkg-format.md
**references/ql-recipes.md**                  the recipes split out of ql-playbook.md
references/workflows/
  single-part-modeling.md                 outline, Role 5 (export), failure routes
  single-part-modeling/**role-1-requirements.md, requirements-template.md, role-2-plan.md,
                        role-3-verifier.md, verifier-contract-patterns.md, role-4-build.md**
  assembly-product-build.md  step-reconstruction.md  engineering-drawing.md  export-and-translation.md
  **scan-reconstruction.md**                  a mesh, point cloud or images as the source
  drawing-reconstruction.md               outline
  drawing-reconstruction/**(role / stage pages, the owner chooses the names)**
references/domains/                       the 11 existing pages (drawing-inspection may gain a template page)
references/discipline/
  **core-rules.md**  **operating-modes.md**  feature-tree-convention.md  notebook-cell-design.md  feature-ordering.md
  geometric-validation.md  datums-and-coordinate-systems.md  mechanical-modeling.md  manufacturing-boundaries.md
  assembly-positioning.md  failure-and-repair.md  requirement-and-cad-brief.md  verifier-scripts.md
references/docs/guides/
  notebook-runtime.md                     run, parameters (<= 300 lines)
  **notebook-composition-and-cache.md**       composing notebooks, the cell cache, library parts
  **product-export.md**                       package export, downstream targets
```

## Checks (`tools/skillbuild.py --check`, tests in `test/test_skill_lint.py`)

1. every path a page names (backticked or in a link, under `references/`) exists;
2. `references/README.md` lists exactly the workflows, domains and discipline pages that exist;
3. every hand-written page is reachable from `SKILL.md` through links;
4. line limits (300 per page, 130 for `SKILL.md`);
5. every workflow has the three sections above and every domain/discipline page has `**Read when:**`;
6. the route table's read set equals the workflow's `Read now` set;
7. the read budget (1,200 compiled lines, see "Workflow pages") for each route and each target;
8. the four curated targets' compiled `SKILL.md` contains the parallel-read instruction;
9. no unresolved `skill:if` / `skill:endif`.

## Changing the skill

Run `python tools/skillbuild.py --check`. To see what a harness gets, `python tools/skillbuild.py --target opencode`
(output goes to `skills/simplecadapi-opencode/`, which git ignores). Behaviour is measured, not assumed: the
agents' traces (Langfuse) give the lines read before the first write and the rules broken; a change that adds reading
needs a reason in its commit message.
