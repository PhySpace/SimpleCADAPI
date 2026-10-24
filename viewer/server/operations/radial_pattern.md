---
label: circular array
category: pattern
api:
  - radial_pattern_rsolidlist
reads:
  - seed feature
  - axis candidate (common instance centers)
  - angular pitch and count
doc_refs:
  - docs/skill/references/docs/api/radial_pattern_rsolidlist.md
  - docs/skill/references/domains/part-modeling.md
---

`radial_pattern_rsolidlist` — fit the axis through instance centroids;
angular pitch = 360/count only for even distributions, otherwise measure.
