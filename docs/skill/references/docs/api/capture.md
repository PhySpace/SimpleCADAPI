# capture

## API Definition

```python
def capture(result: Any, path: str | Path, /, *, include_scene: bool = True) -> CaptureResult
```

*Source: product/capture.py*

## Import Surface

- top-level: `from simplecadapi import capture`

## Description

Capture a durable product and write its canonical `.scadpkg`.

``include_scene=False`` skips the optional Scene projection (tessellated
geometry/entity assets). STEP and MJCF exports read meshes and
feature graphs from the definition closure, so they do not need it.
