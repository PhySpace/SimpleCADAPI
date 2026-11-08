# SimpleWorkplane

`SimpleWorkplane` is a context manager for modeling in a temporary local coordinate frame.

## Public constructor

```python
SimpleWorkplane(
    origin=(0, 0, 0),
    normal=(0, 0, 1),
    x_dir=(1, 0, 0),
)
```

## Main capabilities

- Push a local coordinate frame for nested modeling operations.
- Automatically restore the previous frame when the context exits.
- Keep the public API shape-first: functions still return `Vertex`, `Edge`, `Wire`, `Face`, and `Solid` objects.
- Resolve point parameters relative to the active frame and vector parameters without applying frame translation.
- Compose nested workplanes as a chain: each child `origin`, `normal`, and `x_dir` is expressed in its parent frame.
- Record the fully composed frame on each `GraphSession` node so model JSON replay reproduces the same geometry outside the original context managers.
- Keep existing shape inputs in global coordinates. Entering a workplane does not move a shape; only the operation's point and vector parameters use the active frame.
- Bind declarative sketches to their creation frame, so they can be promoted after the workplane exits without changing position.

## A workplane is a value

- `SimpleWorkplane(...)` (alias `Workplane`) and the recorded constructors below return the same type. It is a frame in
  world coordinates: `wp.origin`, `wp.normal`, `wp.x_dir`, `wp.y_dir` (tuples), `wp.plane` (the sketch-plane mapping
  `{origin, x_axis, y_axis}`), `wp.cs` (its `CoordinateSystem`).
- It can be entered again: `with wp:` in one cell and again in a later cell. Entering the same workplane twice at once is
  an error.
- It pickles (the notebook cell cache stores a cell that defines one), copies, and keeps its graph lineage through both.
- `make_sketch_rsketch(name, plane=wp)` draws a sketch on it: the world frame is used as it is, whatever workplane is
  entered at the time.

## Recorded constructors

| Constructor | The frame |
| --- | --- |
| `make_workplane_rworkplane(origin, normal, x_dir)` | the recorded `SimpleWorkplane(...)` (read in the current system) |
| `make_workplane_from_face_rworkplane(face, *, origin=None, x_edge=None, x_dir=None, offset=0, flip=False)` | on a planar face: its centre (or `origin` projected), outward normal, x along an edge / a direction / the face's own x, moved `offset` along the normal |
| `make_workplane_from_points_rworkplane(a, b, c)` | origin `a`, x towards `b`, normal (b - a) x (c - a); each a `Vertex` or a point |
| `make_workplane_from_axis_rworkplane(axis, angle=0, *, face=None)` | through a straight edge (or a circle's centre line), x along it, turned `angle` degrees about it from `face`'s plane (or the plane square to global Z) |
| `make_workplane_midplane_rworkplane(face_a, face_b)` | halfway between two parallel planar faces |
| `make_workplane_normal_to_curve_rworkplane(curve, at=0, *, x_dir=None)` | normal to an edge or wire at a fraction `at` of its length (a sweep profile's plane) |

Each records its geometry inputs as references. A model-JSON replay builds the frame again from the replayed geometry, so a
sketch on `plane=wp` and every operation made inside `with wp:` follow the face (each such node's context names the
workplane's node; `plane` is recorded as `{"workplane": true, ...frame}` with the workplane node as an input).

## Example

```python
import simplecadapi as scad

with scad.SimpleWorkplane(
    origin=(10, 20, 30),
    normal=(0, 1, 0),
    x_dir=(1, 0, 0),
):
    with scad.SimpleWorkplane(
        origin=(2, 3, 4),
        normal=(1, 0, 0),
        x_dir=(0, 1, 0),
    ):
        box = scad.make_box_rsolid(2, 4, 6)
        moved = scad.translate_shape(box, (0, 0, 2))

print(moved.get_volume())
```

A workplane on a face, a sketch on it, and a boss inside it:

```python
import simplecadapi as scad

base = scad.make_box_rsolid(60, 40, 10, tag_prefix="base")
top = scad.ql.faces().where(scad.ql.tag("base.face.top")).exactly(1).resolve(base)[0]
wp_top = scad.make_workplane_from_face_rworkplane(top, offset=0)

sketch = scad.make_sketch_rsketch("boss", plane=wp_top)
sketch = scad.add_point_rsketch(sketch, "c", 0, 0)
sketch = scad.add_circle_rsketch(sketch, "circle", "c", 8)
boss = scad.extrude_rsolid(scad.make_face_from_sketch_rface(sketch), wp_top.normal, 5)

with wp_top:  # local x, y on the top face, z out of it
    pin = scad.make_cylinder_rsolid(2, 12, bottom_face_center=(20, 0, 0))
```

