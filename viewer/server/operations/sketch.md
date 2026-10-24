---
label: sketch profile
category: sketch
api:
  - make_sketch_rsketch
  - add_line_rsketch
  - add_circle_rsketch
  - add_arc_rsketch
  - constrain_*_rsketch
  - make_face_from_sketch_rface
reads:
  - face plane (origin + normal)
  - boundary edge types, lengths and radii
  - vertex coordinates
doc_refs:
  - docs/skill/references/domains/sketch-and-features.md
  - docs/skill/references/docs/api/make_sketch_rsketch.md
  - docs/skill/references/docs/api/make_face_from_sketch_rface.md
---

Rebuild planar profiles with the constrained sketch API, not loose wires: add
geometry, then constrain until fully constrained, then
`make_face_from_sketch_rface(require_fully_constrained=True)`.
