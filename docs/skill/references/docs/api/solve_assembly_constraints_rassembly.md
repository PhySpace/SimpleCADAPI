# solve_assembly_constraints_rassembly

## API Definition

```python
def solve_assembly_constraints_rassembly(assembly, strict=True)
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import solve_assembly_constraints_rassembly`

## Description

Solve fixed, revolute, and prismatic assembly constraints.

Solving is limit-aware: when a constraint carries a ``ScalarLimit``
(``angle_limit`` or ``distance_limit``), the drive scalar is clamped
into the closed range before placement propagation.  When no drive
scalar is present but a limit exists, the current relative-frame
scalar is projected into the bounds.  Unresolvable closed kinematic
loops fall back to a golden-section search over the limit bounds.

A ``ConstraintReport`` is recorded on the returned assembly under the
``constraint_report`` runtime key for later inspection via
``inspect_assembly_constraints_rassembly``.
