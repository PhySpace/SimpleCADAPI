---
label: mirror
category: pattern
api:
  - mirror_shape
reads:
  - seed feature
  - symmetry plane (pairs of mirrored face centroids)
doc_refs:
  - docs/skill/references/docs/api/mirror_shape.md
  - docs/skill/references/domains/part-modeling.md
---

`mirror_shape(shape, plane_origin, plane_normal)` — fit the symmetry plane
from centroid pairs of mirrored faces, mirror the seed feature, then
`union_rsolid` the halves.
