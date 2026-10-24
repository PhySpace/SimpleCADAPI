---
label: helical sweep
category: solid
api:
  - helical_sweep_rsolid
reads:
  - profile wire
  - helix pitch, height, radius (cylinder axis)
  - handedness (lead-in direction)
doc_refs:
  - docs/skill/references/domains/part-modeling.md
  - docs/skill/references/docs/api/helical_sweep_rsolid.md
---

`helical_sweep_rsolid(profile, pitch, height, radius, handedness)` — for
coils, threads and worm surfaces. The profile plane must contain the helix
axis start; derive pitch from repeated crossing points along one turn.
