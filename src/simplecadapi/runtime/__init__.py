"""The notebook runtime: SimpleCAD models are marimo notebooks.

A notebook whose PEP 723 header has a ``[tool.simplecadapi]`` table
(:mod:`.config`) is a SimpleCAD notebook.  Wherever it runs — the marimo
editor, ``sca run``, :func:`run_notebook` — each cell records into a
session of its own (:mod:`.executor`), cells are the unit of caching, and
the product is the top-level value whose id is the notebook id
(:func:`notebook_id`).  Its
definition is projected from the values (:mod:`.projection`); the
notebook file stays the only source of truth.
"""

from .config import NotebookConfig, NotebookConfigError
from .executor import UnboundRequirementError, notebook_id
from .projection import ProductNotFoundError
from .runner import CellReport, CellStatus, NotebookRun, run_notebook, use

__all__ = [
    "CellReport",
    "CellStatus",
    "NotebookConfig",
    "NotebookConfigError",
    "NotebookRun",
    "ProductNotFoundError",
    "UnboundRequirementError",
    "notebook_id",
    "run_notebook",
    "use",
]
