# make_part_rpart

## API Definition

```python
def make_part_rpart(part_id, body=None, name=None, bodies=None)
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import make_part_rpart`

## Description

Wrap one Solid, or several named solids, as a semantic Part.

``scad.make_part_rpart(part_id=scad.notebook_id(), body=bracket)`` for one solid;
``scad.make_part_rpart(part_id=scad.notebook_id(), bodies={"case": case, "lid": lid})``
for a case and its lid kept as two bodies of one part. Material applies to every
body. Connectors are not supported on multi-body parts yet. Union the solids
first when they must become one body.

## Parameters

### part_id

- **Description**: Stable identifier of the part (``scad.notebook_id()`` in a notebook).

### body

- **Description**: The Solid of a one-body Part. The pieces of a split cut (a list of Solids) become the bodies ``body_1 .. body_n``.

### name

- **Description**: Optional display name.

### bodies

- **Description**: Instead of ``body``: several solids kept apart in one Part, as a mapping ``body_id -> Solid`` (in its order) or a sequence of ``Body`` values. A mapping value may be the pieces of a split cut (a list of

### Solids)

- **Description**: they become ``<body_id>_1 .. <body_id>_n``. Body ids are identifiers, unique within the part. Overlapping bodies are allowed; building the definition warns (``BodyOverlapWarning``).

## Returns

Part: The new Part. ``part.bodies`` lists its bodies; ``part.body`` is the
Solid of a one-body Part.

## Raises

- **SimpleCADError**: Neither or both of ``body`` and ``bodies`` were given, a body is not a Solid, a body id is malformed or repeated, or the part_id is already used.
