# run_notebook

## API Definition

```python
def run_notebook(path: str | Path, *, id: str | None = None, overrides: Mapping[str, Any] | None = None, cache: bool = True) -> NotebookRun
```

*Source: runtime/runner.py*

## Import Surface

- notebook runtime: `from simplecadapi.runtime import run_notebook`

## Description

Run the notebook at *path* and project its product.

*id* replaces the header's id for this run: the product is then the
value with that id, and cells read it with ``notebook_id()``.
*overrides* replace top-level variables: the cells that define them do
not run (marimo requires such a cell's variables to be overridden all
together).  ``cache=False`` neither reads nor writes the cell cache.
Errors raised by a cell propagate unchanged.
