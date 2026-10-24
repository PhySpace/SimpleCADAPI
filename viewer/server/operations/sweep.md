---
label: sweep
category: solid
api:
  - sweep_rsolid
reads:
  - spine wire (tangent continuity)
  - profile wire
  - profile plane vs spine tangent
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/sweep_rsolid.md
---

`sweep_rsolid` — extract the spine as an ordered wire first; check tangent
continuity at spine joints because kinks break the sweep.
