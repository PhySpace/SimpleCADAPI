---
label: fillet
category: modify
api:
  - fillet_rsolid
reads:
  - edge chains
  - edge lengths (sliver filter)
  - dihedral angle at each edge
doc_refs:
  - docs/skill/references/ql-playbook.md
  - docs/skill/references/docs/api/fillet_rsolid.md
---

Read ql-playbook.md Pattern B first: express boolean seam edges structurally
with `ql.edges().incident_to(...)`, never with geometric heuristics, and
fillet immediately after the producing boolean.
