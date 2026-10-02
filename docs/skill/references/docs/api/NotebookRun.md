# NotebookRun

## Class Definition

```python
class NotebookRun(config: NotebookConfig, product: Product, values: Mapping[str, Any], cells: tuple[CellReport, ...], dependencies: frozenset[Path])
```

*Source: runtime/runner.py*

## Import Surface

- notebook runtime: `from simplecadapi.runtime import NotebookRun`

## Description

The outcome of :func:`run_notebook`.

``product`` is the notebook's product and ``definition`` its durable
definition; ``values`` holds every top-level variable, ``cells`` one
report per cell in notebook order, and ``dependencies`` the files
outside the cells the run depends on.
