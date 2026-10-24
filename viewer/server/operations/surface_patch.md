---
label: surface patch
category: surface
api:
  - make_surface_patch_rface
reads:
  - boundary wires
  - adjacent faces (G1 support candidates)
  - boundary continuity
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/make_surface_patch_rface.md
---

`make_surface_patch_rface(SurfaceBoundary ...)` — transcribes a freeform
patch from its boundary; pass support faces only when the original is
tangent-continuous across the boundary.
