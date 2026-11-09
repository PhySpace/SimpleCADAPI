# make_workplane_from_face_rworkplane

## API Definition

```python
def make_workplane_from_face_rworkplane(face, *, origin=None, x_edge=None, x_dir=None, offset=0.0, flip=False)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_workplane_from_face_rworkplane`

## Description

Create a workplane on a planar face of the model.

normal = the face's outward normal (``flip=True`` reverses it); origin = the face's centre, or ``origin``
projected onto the face's plane; x = along ``x_edge`` (its direction at its start, projected onto the plane), or
along ``x_dir`` (projected), or the x direction of the face's own plane. ``offset`` then moves the origin along
the normal (an offset datum plane).

Recorded: the node takes the inputs as ordered references, so a model-JSON replay builds the frame again from the
geometry as it is then, and a sketch on the workplane (``plane=wp``) or an operation inside ``with wp:`` follows it.

``top = scad.ql.faces().where(scad.ql.tag("base.face.top")).exactly(1).resolve(base)[0]``;
``wp = scad.make_workplane_from_face_rworkplane(top, offset=2)``.

## Parameters

### face

- **Description**: A planar Face (picked with ``ql``, ``get_faces(i)`` or a tag).

### origin

- **Description**: A point (current coordinate system) projected onto the face; ``None`` = the face's centre.

### x_edge

- **Description**: An Edge giving the x direction (usually an edge of the face).

### x_dir

- **Description**: A direction giving x; give ``x_edge`` or ``x_dir``, not both.

### offset

- **Description**: Distance along the normal from the face (mm).

### flip

- **Description**: Reverse the normal (draw from inside the body).

## Returns

SimpleWorkplane: a frame in world coordinates (``origin``, ``normal``, ``x_dir``, ``y_dir``, ``plane``) that is
also a context manager: ``with wp:`` makes it the current coordinate system, ``make_sketch_rsketch(plane=wp)``
draws on it. It is a value: enter it again in later code, pickle it (the notebook cell cache does).

## Raises

- **SimpleCADError**: The face is not planar, both ``x_edge`` and ``x_dir`` were given, or the x direction is normal to the face.
