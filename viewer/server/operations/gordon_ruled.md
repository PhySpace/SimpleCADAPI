---
label: gordon / ruled / bezier
category: surface
api:
  - make_gordon_surface_rface
  - make_ruled_surface_rface
  - make_bezier_surface_rface
  - loft_rshell
reads:
  - section wires / point grids
  - surface degree evidence
doc_refs:
  - docs/skill/references/docs/api/make_gordon_surface_rface.md
  - docs/skill/references/docs/api/make_ruled_surface_rface.md
  - docs/skill/references/docs/api/loft_rshell.md
---

Constructive surface family: Gordon for networked sections, ruled for
straight interpolation, `loft_rshell` for shell-preserving lofts. Extract
explicit parameters — never reference the STEP file.
