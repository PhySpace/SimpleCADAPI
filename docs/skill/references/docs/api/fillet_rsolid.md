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

Where a concave and a convex selected edge meet tangentially or nearly so (a post flush with a plate side, a wall a few degrees off it), two rolling-ball bands cannot meet: one ball lies outside the material, the other inside. By default the kernel runs its standard algorithm first and, only at such a junction and only when the standard result fails or is invalid or self-intersecting, closes the junction with the pinch corner: both bands taper along one shared curve on the common face to a single point at the junction vertex (each band an exact variable-radius rolling-ball surface, G1 to its supports and along the shared curve; at the section where the taper starts the bands meet the constant-radius bands with a small crease, about 8 degrees at r = 5 on a post flush with a plate side). If the pinch fails its checks, the Y transition is tried: both bands stop where they touch the shared face and two G1 ribbons join them. A valid standard result is kept. ``strategy_auto_y_patch=True`` takes the Y transition first wherever there is such a junction. Every other edge, and both bands away from the junction, use the standard algorithm; the ribbons are tagged like the bands (``fillet.patch``). Needs a kernel built with the SDK's OCCT patch set (``fillet-robustness-4``); otherwise the flag raises ``ValueError``.
