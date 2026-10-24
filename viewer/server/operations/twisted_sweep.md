---
label: twisted sweep
category: solid
api:
  - twisted_sweep_rsolid
reads:
  - profile face (inner wires included)
  - sweep distance and twist angle
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/twisted_sweep_rsolid.md
---

`twisted_sweep_rsolid(profile, distance, twist_angle)` — for extrusions that
rotate along their axis. Measure the total twist from matching cross-section
features at both ends; inner wires sweep with the profile.
