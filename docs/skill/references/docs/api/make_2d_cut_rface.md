# make_2d_cut_rface

## API Definition

```python
def make_2d_cut_rface(body, tool)
```

*Source: operators/boolean.py*

## Import Surface

- top-level: `from simplecadapi import make_2d_cut_rface`

## Description

Subtract one 2D face from another (2D boolean difference).

## Parameters

### body

- **Type**: `Face`
- **Description**: The face to subtract from.

### tool

- **Type**: `Face`
- **Description**: The face to subtract (the cutter).

## Returns

-------
Face
The resulting face after subtraction.  The result may contain
inner wires (holes) if the tool was fully inside the body.
