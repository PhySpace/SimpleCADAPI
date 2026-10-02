# CellReport

## Class Definition

```python
class CellReport(name: str, key: str, status: CellStatus)
```

*Source: runtime/runner.py*

## Import Surface

- notebook runtime: `from simplecadapi.runtime import CellReport`

## Description

What happened to one cell during a run.

``status`` is ``"ran"`` (executed), ``"cached"`` (restored from the
cell cache) or ``"skipped"`` (not run: overrides replace its variables,
or the cell is disabled).
