# ref.face

## API Definition

```python
def ref.face(feature: str, op: str, *, role: Optional[str] = None, ordinal: int = 0, topo: Optional[str] = None, occurrence: int = 0, slot: int = 0, piece: Optional[int] = None, follow: Follow = 'identity', guard: Optional[Guard] = None, digest: Optional[str] = None, naming: int = 1) -> ElementRef
```

*Source: ref.py*

## Import Surface

- stable references: `import simplecadapi as scad` then `scad.ref.face(...)`

## Description

A reference to a face born in *feature* by *op*.

## Parameters

### feature

- **Description**: The feature (cell) the face was made in: the editor's feature slug, or the cell's namespace.

### op

- **Description**: The operation that made it, as recorded (``"make_box_rsolid"``, ``"make_extrude_rsolid"``).

### role

- **Description**: Its kernel role (``"box.top"``, ``"extrusion.end"``); ``ordinal`` says which when several share it.

### ordinal

- **Description**: Which of the op's faces with that role (0 first).

### topo

- **Description**: For a face without a role: its position in the op's output (``"face_5"``); give a ``guard`` with it.

### occurrence

- **Description**: Which of the feature's *op* operations feeding the shape (0: the first).

### slot

- **Description**: The output of that operation (an operation that makes several solids has one per solid).

### piece

- **Description**: The chosen piece once the face has been split (in the order the split error lists them).

### follow

- **Description**: ``"identity"``; ``"derived"`` also follows into what the face generated.

### guard

- **Description**: ``(geometry type, (x, y, z), area[, normal])`` of the face when it was picked.

### digest

- **Description**: The operation's parameter digest, only when two operations share its name in the feature.

### naming

- **Description**: The naming version the reference was made under (1).

## Returns

ElementRef: The reference; resolve it with ``.one(shape)`` / ``.all(shape)`` / ``.resolve(shape)``.

## Examples

```python
>>> top = scad.ref.face("base", "make_box_rsolid", role="box.top")
>>> top.one(part).get_area()
```
