# fillet_rsolid

## API Definition

```python
def fillet_rsolid(solid, edges, radius, *, result_tag=None, generated_faces_tag=None, strategy_auto_y_patch=False)
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import fillet_rsolid`

## Description

Apply fillets, with optional tagging of kernel-proven patch faces.

``solid`` may also be the list of pieces a cut that split a body returns: each piece gets the picked edges that lie on it, a piece with none is kept as it is, and the result is the list of pieces in the same order. A selector is resolved on every piece and its cardinality (``exactly``/``at_least``/``at_most``) is checked on the edges of all of them.

``strategy_auto_y_patch=True`` turns on the kernel's Y transition: where a concave and a convex selected edge meet tangentially or nearly so (a post flush with a plate side, a wall a few degrees off the plate side), the two rolling-ball bands cannot meet, because one ball lies outside the material and the other inside. With the strategy both bands stop where they touch the shared face and two G1 ribbons, tangent to each other and to both supports, close the junction. Every other edge, and both bands away from the junction, use the standard algorithm; without such a junction, or when the transition fails its validity, self-interference and continuity checks, the standard algorithm runs alone. The ribbons are tagged like the bands (``fillet.patch``). Needs a kernel built with the SDK's OCCT patch set (``fillet-robustness-4``); otherwise it raises ``ValueError``.
