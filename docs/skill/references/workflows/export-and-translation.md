# Workflow: Export and Translation

Take a validated product package and produce the requested downstream
deliverables.

## Preferred command path

For normal delivery, use the package exporter CLI rather than writing a
one-off Python wrapper. It validates the `.scadpkg`, chooses the conventional
output names, prints one JSON report, and lets independent targets finish even
when an optional target is unavailable:

```bash
uv run sca export out/product.scadpkg --output-dir out/exports
```

Without `--format`, this writes AP242 STEP, binary STL, and OBJ. Add unusual
or backend-dependent outputs deliberately; `--check` performs all package,
output-path, and selected-target prerequisite checks without writing files:

```bash
uv run sca export out/product.scadpkg \
  --format fcstd --format mjcf --output-dir out/exports --check
uv run sca export out/product.scadpkg \
  --format fcstd --freecad-cmd /path/to/FreeCADCmd --output-dir out/exports
```

Use the lower-level Python APIs only when a workflow needs behavior the CLI
does not expose, such as consuming a report in-process or a format-specific
option not represented by a CLI flag.

## Goal and scope

Use when geometry and product validation already passed and the remaining
work is format conversion. If the model still needs work, route to the owning
modeling workflow first — exports are deliverables, never validation.

## Task decomposition

```yaml
goal: requested export files from a validated .scadpkg
primary_domain: export-and-translation
required_domains:
  - requirement-refinement   # which formats and why
  - export-and-translation
optional_domains:
  - step-inspection          # roundtrip validation of exports
artifacts:
  - refreshed package (capture re-run if sources changed)
  - sca export JSON report (or API reports for programmatic export)
validation_gates:
  - package is current (sources unchanged since capture)
  - each export report read and printed
  - roundtrip validation when the consumer re-imports STEP
repair_routes:
  - stale export -> re-capture, re-export
  - coarse mesh -> tighten deflection parameters
  - backend missing -> report; no silent format substitution
```

## Steps

1. **Confirm the package is current**: if any source changed since the last
   `capture`, re-run the owning workflow's capture step. Exports are
   point-in-time deliverables. If this workflow edits any part source while
   making it current, the edit follows
   `discipline/feature-tree-convention.md` block structure.
2. **Select targets by consumer contract**
   (`domains/export-and-translation.md` table): editable FreeCAD document →
   `.FCStd`; neutral exchange → AP242 `.step`; DCC/surface inspection →
   `.obj`; additive manufacturing → `.stl`; MuJoCo simulation → MJCF.
3. **Preflight and export from the package path**. Start with
   `uv run sca export <package>.scadpkg --output-dir <dir> --check`.
   It checks the package and default STEP/STL/OBJ targets. Add each non-default
   target with `--format`; FCStd requires FreeCADCmd (or `--freecad-cmd`) and
   MJCF requires an assembly-rooted package. Re-run without `--check` to write
   the files. Use `--output FORMAT=PATH` for a non-conventional file name and
   `--overwrite` only when replacement is intentional.
4. **Read the JSON report**: definition ids, occurrence/solid/triangle counts,
   material items, limitations, and per-target failures. Print the facts;
   never assume success from a missing exception. An unavailable optional
   target returns a nonzero status but does not erase successful independent
   exports.
5. **Validate roundtrip when it matters**: consumers that re-import STEP →
   `validate_step_roundtrip_rdescriptor` on the exported file.
6. **Report**: file paths, per-format report facts, parameters chosen
   (deflection values), and any backend that was unavailable.

## API pages to read

`capture` (when re-capturing), this workflow's CLI command contract, the
exporter page(s) for every format requested when using APIs or interpreting
format-specific reports, the translator page(s) for every backend requested,
and `validate_step_roundtrip_rdescriptor` when roundtrip validation applies.

## Validation gates

- Export report counts match the model's expectation (solids, occurrences,
  triangles).
- Tessellation accuracy chosen deliberately: `linear_deflection` in product
  units, `angular_deflection_degrees` for curved surfaces; tighter for small
  curved parts, looser for large simple geometry when size matters.
- MJCF: every intended joint present; loop-closing constraints emitted as
  equality/connect; public connectors only expose sites/endpoints.
- `.FCStd`: translation consumed the intended package revision.
- `sca export --check` passes before delivery export; the final JSON
  report records every requested target as successful.

## Failure routes

- FreeCAD/FreeCADCmd missing → `sca export --check --format fcstd`
  reports the missing backend before writing. Export default STEP/STL/OBJ if
  requested, offer STEP as the neutral fallback, and say so explicitly.
- STL/OBJ too coarse or too large → adjust deflection parameters, re-export;
  both formats share one tessellation pass.
- MJCF joints missing → the assembly lacked explicit constraints; return to
  `assembly-product-build.md`, do not hand-edit MJCF.

## Deliverables

Exported file paths, report facts per format, chosen parameters, unavailable
backends, and checks not run.

**Required reading before authoring or editing any part source in this
workflow:** `discipline/feature-tree-convention.md` — the block-structured
sketch → basic body op → bool → modifier convention, its mandatory boundary
comments, and the sketch/geometry/primitive tier rules. Every part source
is a marimo notebook, one block per cell
(`references/docs/guides/notebook-runtime.md`): run it with `sca run`, and
load its product from verification scripts with
`simplecadapi.runtime.run_notebook(...)`.
