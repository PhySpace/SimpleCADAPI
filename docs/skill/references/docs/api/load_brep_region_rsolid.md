# load_brep_region_rsolid

## API Definition

```python
def load_brep_region_rsolid(path, sha256, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import load_brep_region_rsolid`

## Description

Load a hash-pinned, target-derived BREP region snapshot as one Solid.

The complete artifact SHA-256 is verified before native BREP decoding. In a
GraphSession, ``path`` must be relative and is replayed relative to the replay
process working directory. Model JSON records the locator and digest, not the
sidecar bytes.
