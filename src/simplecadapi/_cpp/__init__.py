"""SimpleCADAPI on OpenCASCADE, implemented in C++.

The public names mirror ``simplecadapi``; see PORTING_STATUS.md for what exists.
"""

from . import errors
from .errors import SimpleCADError
from ._native import *  # noqa: F401,F403
from ._native import __doc__  # noqa: F401
from ._native import _testing  # noqa: F401  (underscore names are not star-exported)
from ._native import _brep_region, _internal_mesh  # noqa: F401  (underscore names are not star-exported)
from ._native import _constrain_rsketch  # noqa: F401  (graph replay's generic constraint)
from ._native import _brep_region_path  # noqa: F401  (graph replay's locator check)
from ._native import _from_occt, _occt  # noqa: F401  (the OCCT classes of the kept Python layers; see occt/)
