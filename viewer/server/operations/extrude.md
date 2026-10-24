---
label: extrude
category: solid
api:
  - extrude_rsolid
reads:
  - face plane (extrusion direction candidate)
  - profile area
  - side-face height (extrusion distance)
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/extrude_rsolid.md
---

`extrude_rsolid(profile=face, direction, distance)` — measure the distance
from the tagged faces, extrude along the profile normal, and bury joint ends
into the joining body.
