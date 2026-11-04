# ref.of

## API Definition

```python
def ref.of(entity: Any, shape: Any, *, follow: Follow = 'identity', guard: bool = True) -> ElementRef
```

*Source: ref.py*

## Import Surface

- stable references: `import simplecadapi as scad` then `scad.ref.of(...)`

## Description

The stable reference of *entity*, a face, edge or vertex of *shape* (or of a shape *shape* descends from).

The entity is traced back through the recorded history to where it was born, so a face picked on the finished
part is named by the box or extrusion that made it, not by the fillet that last trimmed it.  An edge is named by
the two faces it lies between when that names it in *shape* (``between=``), else by its own birth.

## Parameters

### entity

- **Description**: The picked face / edge / vertex.

### shape

- **Description**: A recorded shape (made inside a ``GraphSession`` or a notebook cell) it belongs to.

### follow

- **Description**: Stored in the reference (see :func:`face`).

### guard

- **Description**: Store the entity's geometric fingerprint (the default; needed for an entity without a kernel role).

## Returns

ElementRef: ``repr()`` is the code that makes the same reference.

## Raises

- **ValueError**: *shape* was not recorded, or *entity* is not part of a recorded output upstream of it.
