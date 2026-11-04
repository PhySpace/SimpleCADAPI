# apply_tag_rselection

## API Definition

```python
def apply_tag_rselection(scope, targets, tag, topology_propagation=<LOCAL: 'local'>, lineage_policy=<CONTINUATION_FRAGMENT: 'continuation_fragment'>)
```

*Source: operators/selection.py*

## Import Surface

- top-level: `from simplecadapi import apply_tag_rselection`

## Description

Return a semantic shape view with a canonical tag assignment.

A tag is also how a face, an edge or a vertex gets a name people read: there is no
second naming system.  Tags resolve through the recorded history, so a tagged face
keeps its name through later features (``ql.tag(...)`` and
``select_faces_by_tag(...)`` find it again); the editor's "name a face" form is this
operation with the picked faces as ``targets``.

``block = scad.apply_tag_rselection(block, scad.ql.faces().where(scad.ql.prop("geom.normal.z", ">=", 0.999)), "lid_seat")``
names the top face; ``scad.ql.faces().where(scad.ql.tag("lid_seat"))`` selects it
later. A body of a Part is named with ``set_body_appearance_rpart(part, body_id, name=...)``.

## Parameters

### scope

- **Description**: The shape the tag is assigned in (a Solid, usually the body).

### targets

- **Description**: What to tag: a ``ql`` selection (``scad.ql.faces().where(...)``) or a list of sub-shapes of ``scope``.

### tag

- **Description**: The name, a normalized token such as ``"lid_seat"`` or ``"role.mounting_surface"``.

### topology_propagation

- **Description**: ``"local"`` tags the targets only; ``"downward"`` also their edges and vertices.

### lineage_policy

- **Description**: How the tag follows the targets through later operations

### (default ``"continuation_fragment"``

- **Description**: kept on continued faces and on the fragments of a split face).

## Returns

AnyShape: A view of ``scope`` with the tag assigned (the same geometry).

## Raises

- **SimpleCADError**: The selection resolved nothing, a target is not inside the scope, or the tag is malformed.
