---
label: cut
category: boolean
api:
  - cut_rsolid
reads:
  - tool volume inside the body
  - resulting wall faces (hole diameter, depth)
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/cut_rsolid.md
---

`cut_rsolid(body, *tools)` — first argument is the body, the rest are tools.
Tangent tools that remove no volume are silently skipped
(`skip_non_intersecting=True`), so verify the cut actually landed by
checking for the new wall faces.
