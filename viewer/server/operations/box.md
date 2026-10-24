---
label: box
category: primitive
api:
  - make_box_rsolid
reads:
  - planar faces (box candidate)
  - bounding box extents
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/make_box_rsolid.md
---

`make_box_rsolid(width, height, depth, bottom_face_center)` — axis mapping is
fixed: width runs along +x (centered), height along +y (centered), depth
along +z starting at the bottom face. Anchor it with the tagged bottom face
center, not the volume centroid.
