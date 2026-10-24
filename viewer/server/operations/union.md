---
label: union
category: boolean
api:
  - union_rsolid
reads:
  - operand overlap regions
  - resulting seam edges
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/union_rsolid.md
---

`union_rsolid(*solids)` — FTC dataflow `body = union(body, tool)`; it fails
explicitly unless exactly one merged solid results. Tag the fresh seam edges
immediately after the union if a blend follows.
