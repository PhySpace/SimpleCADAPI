# make_sketch_rsketch

## API Definition

```python
def make_sketch_rsketch(name=None, *, plane='XY', sketch_id=None)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import make_sketch_rsketch`

## Description

Create an empty declarative sketch document.

Use this API, not concrete edge/wire constructors, when the intent is to
build a sketch profile with constraints.
