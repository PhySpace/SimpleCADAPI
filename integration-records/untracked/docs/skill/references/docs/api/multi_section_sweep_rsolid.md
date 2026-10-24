# multi_section_sweep_rsolid

## API Definition

```python
def multi_section_sweep_rsolid(sections: Sequence[Union[Wire, Vertex]], path: Wire, *, frame_policy: str = "corrected_frenet", with_contact: bool = False, with_correction: bool = False, auxiliary_spine: Optional[Wire] = None, curvilinear_equivalence: bool = True, auxiliary_contact: str = "none", tracking_policy: TrackingPolicy | str = TrackingPolicy.FULL, tag_prefix: Optional[str] = None, result_tag: Optional[str] = None, start_face_tag: Optional[str] = None, end_face_tag: Optional[str] = None, side_faces_tag: Optional[str] = None) -> Solid
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import multi_section_sweep_rsolid`

## Description

Sweep two or more ordered closed Wire sections along one path and close the result as a Solid. A Vertex may replace only the first or last section to create a point terminal.

`frame_policy` is `corrected_frenet`, `frenet`, or `auxiliary_spine`. An auxiliary spine controls the moving frame; it is not an arbitrary guide rail and does not guarantee that the result boundary passes through that curve.

## Example

```python
from simplecadapi import (
    make_line_redge,
    make_rectangle_rwire,
    make_wire_from_edges_rwire,
    multi_section_sweep_rsolid,
)

path = make_wire_from_edges_rwire([make_line_redge((0, 0, 0), (0, 0, 20))])
sections = [
    make_rectangle_rwire(8, 6, center=(0, 0, 0), normal=(0, 0, 1)),
    make_rectangle_rwire(12, 8, center=(0, 0, 10), normal=(0, 0, 1)),
    make_rectangle_rwire(6, 4, center=(0, 0, 20), normal=(0, 0, 1)),
]
solid = multi_section_sweep_rsolid(sections, path, with_correction=True)
```
