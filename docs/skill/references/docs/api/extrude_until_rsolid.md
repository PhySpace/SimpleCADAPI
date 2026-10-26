# extrude_until_rsolid

## API Definition

```python
def extrude_until_rsolid(profile: Face, target: Solid | Sequence[Solid], direction: Sequence[float] = (0, 0, 1), until: str = 'NEXT') -> Solid
```

*Source: operators/limited_extrusion.py*

## Import Surface

- top-level: `from simplecadapi import extrude_until_rsolid`

## Description

Extrude a planar face until a target surface, including curved surfaces.

NEXT and LAST select the nearest and farthest forward contact. PREVIOUS
and FIRST reverse the direction and select the nearest and farthest contact
behind the profile. Target surfaces must cover the profile at the contact;
an uncovered/open or disconnected output is rejected. Every target remains
a graph input, so changes to target geometry replay this feature correctly.
