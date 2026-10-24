---
label: intersect
category: boolean
api:
  - intersect_rsolid
reads:
  - operand overlap volume
  - shared boundary faces
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/intersect_rsolid.md
---

`intersect_rsolid(*solids)` — keeps only the shared volume. Useful to trim a
transcription overshoot back to the target envelope; tag the shared boundary
faces it produces.
