---
label: cone
category: primitive
api:
  - make_cone_rsolid
reads:
  - conical face (half angle, axis)
  - bottom / top circle radii
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/make_cone_rsolid.md
---

`make_cone_rsolid(bottom_radius, height, top_radius, bottom_face_center,
axis)` — `top_radius > 0` gives a truncated cone (frustum); measure both end
radii and the axis from the tagged conical face.
