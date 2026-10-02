# Discipline: Assembly Positioning

How SimpleCADAPI represents mating and motion intent, plus engineering guidance
for choosing frames and placements.

## Evidence labels

- **SDK contract** below describes behavior implemented by the public assembly,
  connector, placement, and solver APIs.
- **Modeling guidance** is a design recommendation. It is not automatically
  enforced by the SDK and must be reported as an assumption when it affects fit.

## Core rule

Positioning is authored in source — part-local frames, connectors on leaf
parts, placements, declarative constraints — and validated after solving. It
is never eyeballed in a viewer and never patched into exported geometry.

## The intent ladder

From weakest to strongest expression:

```text
raw numeric placement
→ placement tied to a named datum/offset/clearance
→ connector frames on leaf parts (mating interface as data)
→ declarative constraints (fixed/revolute/prismatic/gear/rack-pinion/belt)
→ grounded root + solved constraint graph
```

Use the strongest expression the relationship actually has. A lid seated on a
base with a gasket gap is a constraint-bearing relationship, not a matrix.

## Terminology

- **Placement** is a canonical right-handed frame created by
  `make_placement_rplacement(origin, x_axis=(1,0,0), y_axis=(0,1,0))` or
  `identity_placement_rplacement()`. Inputs are interpreted in the active
  `SimpleWorkplane` and transformed to global coordinates. The public API does
  not accept Euler, quaternion, or axis-angle payloads.
- **Connector** is a named frame owned by a leaf part
  (`add_connector_rpart`, `make_placement_connector_rconnector`,
  `make_edge_connector_rconnector`, `make_face_connector_rconnector`,
  `make_vertex_connector_rconnector`).
- **Public connector** is an interface declaration on an assembly
  (`set_public_connector_rassembly`): public id + direct-child component and
  connector reference. Declaring it does not clone, offset, or move geometry.
  When consumed through nested assemblies, the resolver follows nested public
  declarations to the source connector; it is not limited to one nesting level.
- **Constraint** is the design relationship: flush, centered, coaxial,
  hinge-like, slider-like, gear mesh, rack drive, belt drive.

## Choosing constraint types

| Relationship | Constraint |
| --- | --- |
| Fixed mounting, root grounding | `add_fixed_constraint_rassembly` / `ground_component_rassembly` |
| Hinge, pivot, rotational pose | `add_revolute_constraint_rassembly` |
| Slider, telescoping motion | `add_prismatic_constraint_rassembly` |
| Gear mesh (ratio, axes) | `add_gear_constraint_rassembly` |
| Rack and pinion | `add_rack_pinion_constraint_rassembly` |
| Belt/pulley relation | `add_belt_constraint_rassembly` |

Ground at least one component — the solver requires a grounded component to
seed placements. Multiple grounded components are accepted, but can
overconstrain the system or fail residual verification; ground exactly the
components that are truly fixed in the product frame.
**Modeling guidance:** when a body is authored away from the assembly origin,
rotate it about its intended local axis before applying the translation. This
avoids an unintended orbit around the assembly origin; it is a source
construction choice, not a separate Placement API requirement.
When a public connector declaration, source connector, or resolved frame
changes, dependent interface hashes and builds are invalidated intentionally;
that is dependency propagation, not a solver error.

## Nesting

- **Modeling guidance:** group a functional unit (a bearing, gearbox stage, or
  fastener set) into a subassembly when it is placed, reasoned about, or
  repeated as a unit.
- A parent consumes a nested subassembly through its public connectors. The
  resolver can follow nested public declarations to the source connector, but
  a parent constraint does not automatically make an internal component
  independently movable. Author and solve the nested mechanism's own
  constraints first.
- Public ids are unique within their assembly. Changing a declaration, its
  source, or its resolved frame changes the interface hash and invalidates
  dependent builds.

## Authoring workflow

1. Choose the fixed/root component; ground it.
2. Define part-local frames and datums before placing children
   (`datums-and-coordinate-systems.md`).
3. Attach connectors on leaf parts at functional datums.
4. Compose with placements; declare public connectors where a parent will
   consume a subassembly.
5. Add declarative constraints for mating and motion.
6. Solve; read residuals
   (`measure_constraint_residual_rconstraintresidual`) and
   `inspect_assembly_constraints_rconstraintreport`.
7. Validate placement outcomes with measurements, not impressions.

## Positioning validation checklist

- Mating faces measure flush (or at the specified gap/offset).
- Screw/bore axes measure coaxial; X/Y positions match.
- Repeated parts share orientation; each occurrence lands at its named
  position.
- Moving a component changed placement only — its solid is untouched
  (compare volume/bounds before and after if in doubt).
- Solve residuals within tolerance; hits/misses match expectations.

## When a check fails

Fix in source, in this order of likelihood: part-local origin or datum;
connector frame definition; placement translation/rotation; constraint
reference (wrong component or connector); missing or conflicting constraint;
assembly hierarchy. Then re-solve and re-validate. Never patch the solved
output.
