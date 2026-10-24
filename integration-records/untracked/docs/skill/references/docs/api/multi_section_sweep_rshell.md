# multi_section_sweep_rshell

## API Definition

```python
def multi_section_sweep_rshell(sections: Sequence[Union[Wire, Vertex]], path: Wire, *, frame_policy: str = "corrected_frenet", with_contact: bool = False, with_correction: bool = False, auxiliary_spine: Optional[Wire] = None, curvilinear_equivalence: bool = True, auxiliary_contact: str = "none", result_tag: Optional[str] = None, start_edges_tag: Optional[str] = None, end_edges_tag: Optional[str] = None, side_faces_tag: Optional[str] = None) -> Shell
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import multi_section_sweep_rshell`
- surface namespace: `from simplecadapi.surface import multi_section_sweep_rshell`

## Description

Sweep two or more ordered Wire or endpoint-Vertex sections along one path and return the open side Shell. Use this API when caps are not required or while diagnosing section/path compatibility.

`frame_policy="auxiliary_spine"` accepts one auxiliary Wire that controls section orientation. This is a frame-control spine, not a general multi-rail boundary constraint.

Because the open PipeShell stores endpoint contours as boundary Edge subshapes rather than one composite Wire subshape, `start_edges_tag` and `end_edges_tag` tag the complete endpoint edge sets.
