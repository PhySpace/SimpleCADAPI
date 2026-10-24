---
label: fill holes
category: surface
api:
  - fill_holes_rshell
  - free_boundaries_rwirelist
reads:
  - free boundaries of the shell
  - hole perimeter wires
doc_refs:
  - docs/skill/references/docs/api/fill_holes_rshell.md
  - docs/skill/references/docs/api/free_boundaries_rwirelist.md
---

For open shells: enumerate holes with `free_boundaries_rwirelist`, then
`fill_holes_rshell`. Verify closure externally, not in the modeling script.
