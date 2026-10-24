---
label: revolve
category: solid
api:
  - revolve_rsolid
reads:
  - profile face
  - axis candidate (cylinder axes, face plane normals)
  - angular extent
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/revolve_rsolid.md
---

`revolve_rsolid(profile, axis)` — confirm the axis from cylindrical face
axes or coaxial circle centers before revolving a full turn.
