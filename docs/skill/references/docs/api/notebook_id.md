# notebook_id

## API Definition

```python
def notebook_id() -> str
```

*Source: runtime/executor.py*

## Import Surface

- top-level: `from simplecadapi import notebook_id`

## Description

Return the id of the notebook run the calling cell belongs to.

It is the header's ``id`` unless the run was started with another
(``run_notebook(path, id=...)``, ``use(path, id=...)``), so a notebook
that names its product with it describes a part family: each id is one
member, with a definition of its own.
