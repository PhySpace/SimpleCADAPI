# explode_rassembly

## API Definition

```python
def explode_rassembly(assembly, factor, *, center=None, axis=None, directions=None, weights=None)
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import explode_rassembly`

## Description

Return a display copy of an assembly with its components pushed apart for an exploded view.

Each top-level component moves by ``factor * weight * direction * size``: ``size`` is the diagonal of the box that
holds every component's bodies, ``weight`` is ``weights[component_id]`` (default 1; list a component with 0 to keep
it, for example the grounded base) and ``direction`` is ``directions[component_id]`` (normalised), else ``axis``
(signed by the side of the centre the component is on), else the vector from the centre to the component's own
centre (the centre of the box of its bodies). ``center`` overrides the assembly centre (the centre of the box of
all components). A component with no direction (it is at the centre, or on the centre plane of ``axis``) stays and
is listed in ``get_metadata("explode")``, together with factor, size, centre and every displacement. ``factor=0``
gives the same placements. Parts, constraints, grounding and public connectors are untouched and the constraints
are not re-solved: the result is a placement set for display, rendering and export, and solving it moves the
components back.
