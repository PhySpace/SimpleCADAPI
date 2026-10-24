---
label: sphere
category: primitive
api:
  - make_sphere_rsolid
reads:
  - spherical face (radius, center)
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/make_sphere_rsolid.md
---

`make_sphere_rsolid(radius, center)` — full sphere only; partial balls must
be trimmed with `intersect_rsolid` afterwards. Read radius and center from
the tagged spherical face.
