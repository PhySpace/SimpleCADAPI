---
label: shell (hollow)
category: modify
api:
  - shell_rsolid
reads:
  - faces to keep open (removal candidates)
  - wall thickness (pair of parallel offset faces)
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/shell_rsolid.md
---

`shell_rsolid(solid, faces_to_remove, thickness)` — hollows the body and
opens it at the removed faces. The product is still a solid: pick the open
faces first, then measure thickness from the distance between the paired
original/offset wall faces.
