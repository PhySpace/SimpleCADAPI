# run_notebook

## API Definition

```python
def run_notebook(path: str | Path, *, id: str | None = None, overrides: Mapping[str, Any] | None = None, cache: bool = True, through: int | None = None, product: bool = True, timeout: float | None = None) -> NotebookRun
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

*through* runs only the first *through* cells, in notebook order — the
validation of a stage the tail does not have to exist for.  With
``product=False`` the run does not look for the notebook's product at
all.  *timeout* (seconds) fails the run with :class:`TimeoutError` when
it takes longer; ``None`` (the default) runs unbounded.
