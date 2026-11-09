# fillet_rsolid

## API Definition

```python
def fillet_rsolid(solid, edges, radius, *, result_tag=None, generated_faces_tag=None)
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import fillet_rsolid`

## Description

Apply fillets, with optional tagging of kernel-proven patch faces.

``solid`` may also be the list of pieces a cut that split a body returns: each piece gets the picked edges that lie on it, a piece with none is kept as it is, and the result is the list of pieces in the same order. A selector is resolved on every piece and its cardinality (``exactly``/``at_least``/``at_most``) is checked on the edges of all of them.
