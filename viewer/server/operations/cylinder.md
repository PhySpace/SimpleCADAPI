---
label: cylinder
category: primitive
api:
  - make_cylinder_rsolid
reads:
  - cylindrical face (radius, axis)
  - circle edges (radius, center)
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/make_cylinder_rsolid.md
---

`make_cylinder_rsolid(radius, height, bottom_face_center, axis)` — read
radius from the tagged cylindrical face and the axis from its surface
normal; height from the extent along the axis.
