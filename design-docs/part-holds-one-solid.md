# A Part holds exactly one solid (the multi-body Part is withdrawn)

Status: decided on 2026-11-10 and implemented on branch `fix/part-holds-one-solid`. This document **supersedes**
`multi-solid-design.md`. Read it first; the older document is kept only as the record of what was tried.

It is written so that someone who was not in the conversation can see what was decided, why, what was rejected,
and which commit carries which part. The commit messages of the series repeat the reasons in short.

## 1. What was decided

**A `Part` is one solid. Nothing else is a Part.**

- Several solids that exist side by side while a model is built (a tool and its target, the tools of a pattern before
  the cut) are **loose values of a notebook**. The editor and the preview show them; they are not a product item, so
  nothing places, mates, exports or weighs them as one thing.
- A deliverable that really is several solids is an **Assembly of Parts**: one Part per solid, identity placements.
- The Part constructor refuses anything but one solid, in the lowest layer (C++), so that no consumer has to branch.

## 2. The discussion it comes from (owner and assistant, 2026-11-10)

This is the reasoning that matters; keep it when the code changes.

**The need that created the multi-body Part (the owner).** The editor must support several solids existing in one
notebook, with no assembly constraint between them. This is easy to understand: to pattern a tool and then cut, there
is necessarily a moment where more than one tool and the body exist together. At the time a Part was the only product
value a notebook could end in, so the Part was made to hold several named bodies.

**The owner's judgement.** That choice makes assembly hard. The whole design was made for a human-friendly editor,
and it led to a very wrong decision: designing a multi-solid Part. The owner asked whether we should go back to
"a Part has exactly one solid" and support the human-friendly editor by some other, better means.

**The assistant's analysis, accepted by the owner.**

1. The solids side by side in the pattern-then-cut example are *intermediate values of a notebook*, not product
   items. A Part is a line of the bill of materials and the unit an Assembly places, mates and gives connectors to.
   "The working set of solids while modelling" and "the product" are two levels that were mixed into one type.
2. So the editor's need is a *preview / notebook-value* need (show every open solid), not a Part need. The runtime
   already had the pieces: `cut_rsolid` returns `Pieces`, a pattern returns a solid list, and the scene had a
   shape-root path.
3. The honest exit from "several solids" to a deliverable is an Assembly (`split_rpart` in the old design was
   exactly that exit).
4. Keeping multi-body and finishing connectors (a connector anchored by `body_id` + entity) was costed and rejected:
   it changes the part-definition contract, the interface / binding hashes and the entity bindings, and still leaves
   a type that overlaps with Assembly ("an assembly without constraints").

**Urgency (the owner).** The multi-body Part might be a malignant bug of the released 2.2.8, so the audit and the
change were to start at once, and the GitHub release `v2.2.8` was deleted (the tag `v2.2.8` still exists on origin;
a PyPI upload, if there was one, is not undone by that).

**How to work (the owner).** One commit per decision, and every commit message states the chain of the decision and
its reasons, so that anyone can take over and trace it later. Split decisions as finely as sensible.

## 3. What the audit found in 2.2.8 (code read and run, 2026-11-10)

| Finding | Where | Effect |
|---|---|---|
| Connectors on a multi-body Part are refused | `Part` constructor (`part.cpp`) | no mate, public connector or `ConnectorRef` can reach one; it joins an assembly only as a rigid blob placed by its origin |
| `explode_rassembly` raises `TypeError` | `ops_explode.cpp` `collect_box` calls `Part::body()` | any assembly holding a multi-body Part cannot be exploded |
| the scene compiler reads `part.body` | `scene/compiler.py` (4 places) | `compile_scene` fails on a multi-body Part |
| `build/definition.py` passed `part.body` to the connector interface | `definition.py` | would break the moment connectors were allowed |

What still worked: a multi-body Part as a component with a placement, flattening an assembly to a compound, the
preview, STEP, mass, the package and the cell cache. Not checked: joint / constraint solving, interference, MJCF
(they depend on connectors, which a multi-body Part could never have).

One-body Parts were not affected by any of this.

## 4. The design after the decision

| Concern | Rule |
|---|---|
| Part | exactly one solid; `Part.body` always works; `Part.bodies` is a one-element tuple kept because `Body` carries the display name, colour and opacity (`set_body_appearance_rpart`) |
| `make_part_rpart` | `body=` a Solid, a `Body`, or a list of exactly one piece; `bodies=` does not exist; several pieces raise `ValueError` that says what to do |
| Part definition (durable) | profile 2, one solid; profile 3 and `solid_cache.bodies` are removed (they only ever shipped in the withdrawn 2.2.8) |
| Notebook with several open solids | no product is chosen for the author: `find_product` raises `SeveralOpenBodiesError` naming the solids and what to do |
| Preview of such a notebook | the open solids are drawn side by side (`compile_open_bodies`, node ids `node/<notebook id>/body:<name>`), so the editor keeps what it needed |
| Several solids as a deliverable | an Assembly of Parts |
| `inspect_body_overlaps_rlist`, `BodyOverlapWarning`, `part_shape`, `part_from_bodies` | removed: they only existed for a Part of several bodies |
| `measure_part_mass_rmassreport` | kept; one row per Part |

`Pieces` (the result of a splitting `cut_rsolid`, and fillet / chamfer / per-piece operations) is unaffected: it is a
notebook value, which is where several solids belong.

## 5. The commits of the series (decision by decision)

Each line is one decision; the commit message holds its reasons.

1. `part: a Part holds exactly one solid` - the invariant, in C++ and the bindings.
2. `python glue + replay: follow the one-solid Part` - pickling through `Body`; replay refuses a recorded multi-solid Part.
3. `artifacts: a part definition holds one solid` - drop profile 3 and `solid_cache.bodies`.
4. further commits (preview of open solids, runtime product rule, removal of the helpers, scene / exporters, editor,
   tests, docs) are listed in `git log fix/part-holds-one-solid` after the commit that adds this file.

## 6. Open points

- Whether anything outside this repository (a PyPI upload of 2.2.8, the editor plugins) must be withdrawn or
  re-released is a release decision, not made here.
- The tag `v2.2.8` was left in place; moving or deleting it is the owner's call.
