"""Product and assembly semantic value model plus its persistence layer.

Value classes: ``Placement`` → ``Connector`` → ``Constraint``/``Material``/
``Part`` → ``Assembly``, assembly solving (``solver``), and the canonical
persistence pipeline (``occurrence`` → ``packages`` → ``capture``).
"""

from .placement import Placement
from simplecadapi._cpp import (
    Assembly,
    Component,
    Connector,
    ConnectorAnchor,
    ConnectorRef,
    Constraint,
    ConstraintReport,
    ConstraintResidual,
    GeometryRef,
    Material,
    Part,
    PublicConnectorRef,
    ScalarLimit,
)

__all__ = [
    "Assembly",
    "Component",
    "Connector",
    "ConnectorAnchor",
    "ConnectorRef",
    "Constraint",
    "ConstraintReport",
    "ConstraintResidual",
    "GeometryRef",
    "Material",
    "Part",
    "Placement",
    "PublicConnectorRef",
    "ScalarLimit",
]
