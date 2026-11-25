# Optional single-part drawing workflow

## Decision

In the 2026-11-18 integration request, the user asked to turn dxf-exporter into
a reviewable SimpleCADAPI contribution and compare it with the existing drawing
tool. Integrate the workflow behind `sca drawing` and reuse the existing
declarative engine. The optional workflow selects inputs for that engine and
preserves its independent measurements and verification.

`SheetPlan` can accept a different projection implementation through a protected
view hook. Both paths use a single vector DXF builder. The direct `SheetPlan`
entry point continues to accept its existing declarations, and its rendering
continues to use its existing behavior. The workflow can add decorations,
verify the saved DXF, and rasterize it once at a bounded resolution.

## Capabilities and ownership

| Decision | Reason |
| --- | --- |
| Separate `dxf_engine.workflow` and one CLI group | Preserve the existing low-level solver contract and keep the STEP/notebook entry discoverable alongside `sca run`. |
| Measure the physical solid | AP242 presentation geometry can be part of the imported compound. Extents are calculated on the solid and dimension geometry is read back. |
| Cache projections within one plan | View scoring, dimension proposals and fit trials reuse geometry without global caches or changes to owner state. |
| Use the existing optional `verify` dependency for polygonal HLR | Some spline-heavy parts have expensive exact projections. Point and face measurements still come from the original B-Rep. The workflow reports the approximation. |
| Preserve a notebook STEP and parameter ledger | The agent can edit and replay a declaration while the SDK measures the feature. A missing or mismatched binding remains an explicit review item. |
| Keep inspection workflows separate from drafting decisions | Shared-layout DXFs and overlays preserve the geometry inspection use case. |

The contribution avoids a second solver, a separate DXF writer for core
entities, new mandatory dependencies and generated CAD assets in Git. Templates
are drafting starting points. Manufacturing completeness, PMI ingestion and
assembly drawings remain separate work.
