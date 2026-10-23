# Unit

## Class Definition

```python
class Unit(symbol, dimension, scale_to_canonical)
```

*Source: params/units.py*

## Import Surface

- top-level: `from simplecadapi import Unit`

## Description

Named unit with a scale to SimpleCAD's canonical numeric units.

Custom units are supported and serialize their symbol, dimension, and scale.
Registered built-in units serialize as compact symbols.
