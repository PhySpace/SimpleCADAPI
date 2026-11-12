# Compound

`Compound` is an explicit multi-shape projection wrapper.

SimpleCADAPI 2.0 beta keeps integrated modeling centered on single `Solid`
results, but product-level `Assembly` workflows can be projected into a flattened
`Compound` with `make_compound_from_assembly_rcompound(...)`.

The stable public geometry wrapper surface is:

- `Vertex`
- `Edge`
- `Wire`
- `Face`
- `Solid`
- `Compound`

Use `Compound` when a workflow intentionally needs a flattened geometry
projection. Do not use it as a substitute for `Assembly` product structure.

For normal part modeling, keep using `Solid` as the body-level geometry. A
`Part` wraps exactly one `Solid`. A `Compound` built from solids does not keep
their tags, so it is not a way to hold several solids as one Part: make one Part
per solid and an Assembly of them.
