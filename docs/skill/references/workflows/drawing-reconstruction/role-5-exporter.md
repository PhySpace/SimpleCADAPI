# Drawing Reconstruction: Role 5, Exporter

Part of `workflows/drawing-reconstruction.md`. Load when the roundtrip has passed.

## Role 5 — Exporter

Read the export rows from `REQUIREMENTS.md`. Durable canonical delivery is
`sca run <part>.py --out out/<part>.scadpkg` (or
`capture(run.definition, ...)` after `run_notebook`); external formats through
`domains/export-and-translation.md`. Post-export gate: re-open the package
in a fresh process and confirm definition/solid counts; list every produced
file with size.

Final delivery ⛔: evidence pack — `report_A.md`, `report_B.md`, the diff
table, calibration records, provenance viewports, sheet B renders — plus
assumptions made, checks not run, and the process-note remarks from the
technical-requirements classification. Record the user's verdict; a
rejection routes back through the role map to the owning artifact.

**Unattended:** the final-delivery gate binds the evidence pack, not a person: attach it to `report.md` together with
the assumptions, the checks not run and the process-note remarks, and state the result of the roundtrip. No verdict is
recorded as an approval; the service's own validation is the verdict.
