---
label: loft
category: solid
api:
  - loft_rsolid
reads:
  - section wires in order
  - section areas and orientations
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/loft_rsolid.md
---

`loft_rsolid(sections)` — order the sections along the flow direction;
sections of wildly different edge counts will produce multi-patch faces.
