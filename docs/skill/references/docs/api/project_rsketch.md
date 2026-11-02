# project_rsketch

## API Definition

```python
def project_rsketch(sketch, source, *, entities=None, construction=True)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import project_rsketch`

## Description

Bring geometry from another sketch, or from the edges of shapes, into the sketch as reference geometry.

``source`` is a Sketch (any plane; it is solved first), a Solid / Face / Shell / Wire / Edge / Compound or a list
of shapes (what ``ql.edges().resolve(shape)`` returns). Points go through the plane frames: u = (P - origin) .
x_axis, v = (P - origin) . y_axis. Points, lines, circles and arcs in a parallel plane are copied (an arc keeps its
counter-clockwise sense); a circle or arc seen edge on becomes a line, a line along the sketch normal a point, an
oblique full circle an ellipse; an oblique arc, and edges that are not lines or circles, are refused by name.
``entities`` limits the source sketch entities (default: all lines, circles, arcs and free points; ellipses and
B-splines are skipped and listed in ``get_metadata("last_edit")``); it is not used with shapes. The copies are
``construction`` (default True) and fixed at their projected coordinates. Ids are ``proj_<source sketch id>_<n>``
(``proj_shape_<n>`` for shapes); ``get_metadata("projections")`` lists {source, entity, projected} and projecting
the same source again reuses the entities already there.
