# STEP recognition regression set

The 17 input STEP files and their paths are listed in the external
`compare/merge-1024/measurements.json` manifest. The files are not copied into
this repository. `step-recognition-17-current.json` records the input hashes and
the current recognizer's results, so a later run can be compared against the
same bytes.

From the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.\.venv\Scripts\python.exe tools/step_recognition_benchmark.py `
  --measurements D:\Code\step-feat\feat\compare\merge-1024\measurements.json `
  --output out/step-recognition-current.json --version input --timeout 20
```

The runner isolates each case in a child process. A timeout or error is a gap,
not a zero-candidate result. The output includes the input hash, recognized
categories, candidate count, unowned face count, and elapsed time. Run with
`--version merge_1024` to inspect that version's reconstructions. Inspect
changed classifications against the STEP geometry; candidate counts alone do
not establish correctness or recover the original modeling history.

Current input results: `arch_beam` is one whole-body loft, while
`apple_loft`, `concept_hairdryer`, `grooved_block`, and `twisted_ring` have no
automatic candidate. All 17 complete within the 20-second per-case budget.
These four cases remain explicit recognition gaps. On the triangulated
`twisted_ring`, the earlier 138 planar chamfer candidates are now zero; the
full eight-kind analysis takes about 16 seconds on this machine.

`step-reconstruction-accuracy-current.json` remeasures three reconstruction
accuracy regressions with the current SDK and records the target and candidate
STEP hashes. This recognition baseline does not resolve their candidate geometry:

| Case | merge-1015 volume error | merge-1024 volume error | Next candidate to test |
| --- | ---: | ---: | --- |
| `arch_beam` | 0.061% | 1.0716% | Use the recovered curved guide proxy and changing sections; compare against the prior section fit. |
| `concept_hairdryer` | 0.000041% | 0.0225% | Recheck the nozzle, handle, and inner passage sections from the older parametric candidate. |
| `twisted_ring` | about 0% | 3.6704% | Rebuild the faceted ring from a ruled triangular panel law and compare material in both directions. |

The table rounds the fresh global measurements; the referenced comparison
report first identified these regressions. Global measurements are not strict
acceptance results. Keep each candidate editable and generated without copying
target faces. Promote a new candidate only after package replay, STEP
roundtrip, valid bidirectional material comparison, and the feature checklist
pass.
