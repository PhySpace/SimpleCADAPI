"""Helpers the standard-library modules written in Python (``std/bearing.py``) need."""

from __future__ import annotations

import functools
from typing import Any


def graph_tracking_scope(factory: Any) -> Any:
    """Decorator: the factory builds under the graph tracking policy (its operations are recorded as graph nodes)."""

    import simplecadapi._cpp as nat

    @functools.wraps(factory)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with nat.tracking_policy_scope(nat.TrackingPolicy.GRAPH):
            return factory(*args, **kwargs)

    return wrapped
