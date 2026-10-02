# part

## API Definition

```python
def part(func: Callable[_P, _R] | None = None, *, id: str | None = None, revision: str = '1.0.0', inputs: Sequence[FileInput] = (), project_root: str | Path | None = None, tolerance_profile: str = 'simplecad-default') -> Callable[[Callable[_P, _R]], Callable[_P, PartBuildResult]] | Callable[_P, PartBuildResult]
```

*Source: build/part_builder.py*

## Import Surface

- top-level: `from simplecadapi import part`

## Description

Decorate one synchronous builder as a single-solid product part.

Every call runs the builder in a fresh session of its own and returns a
``PartBuildResult``. The call may happen while another session is
recording (a notebook cell, an ``@assemble`` body): that session is set
aside for the build, and the returned Part appears in it as an external
definition when it is used there.
