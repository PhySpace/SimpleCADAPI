# make_material_rmaterial

## API Definition

```python
def make_material_rmaterial(material_id, name=None, density=None, density_unit=None, color=None)
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import make_material_rmaterial`

## Description

Create a material definition for later Part assignment.

Material is deliberately separate from `make_part_rpart(...)`; the only
correct workflow is to create a material and then assign it to a Part with
`assign_material_rpart(...)`.
