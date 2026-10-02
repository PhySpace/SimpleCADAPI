# use

## API Definition

```python
def use(path: str | Path, /, *, id: str | None = None, **overrides: Any) -> Product
```

*Source: runtime/runner.py*

## Import Surface

- top-level: `from simplecadapi import use`

## Description

Run the notebook at *path* and return its product.

A relative *path* is relative to the notebook calling ``use``.  *id*
replaces the child's header id (see :func:`run_notebook`); the other
keyword arguments override the child's top-level variables.  The product
carries its definition, so it can be a component of an assembly
directly; the calling notebook's cache now depends on the child.
