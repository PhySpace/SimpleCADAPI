# load_brep_region_rshell

## API Definition

```python
def load_brep_region_rshell(path, sha256, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import load_brep_region_rshell`

## Description

Load a hash-pinned, target-derived BREP face region as one Shell.

The Shell keeps target-derived topology and is tagged with imported-sidecar
provenance. Use ordinary replayable surface operations to join it to fitted
or analytic feature faces. GraphSession requires a relative sidecar path.
