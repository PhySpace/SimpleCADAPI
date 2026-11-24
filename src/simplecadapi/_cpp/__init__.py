"""SimpleCADAPI on OpenCASCADE, implemented in C++.

The public names mirror ``simplecadapi``; see PORTING_STATUS.md for what exists.
"""

import os as _os

# A development prefix can be shared OCCT; Windows deliberately ignores PATH when
# resolving extension dependencies. Keep this handle alive for delayed toolkit loads.
_prefix = _os.environ.get("SCAD_OCCT_PREFIX")
if _os.name == "nt" and _prefix and _os.path.isdir(_bin := _os.path.join(_prefix, "bin")):
    _occt_dll_directory = _os.add_dll_directory(_os.path.abspath(_bin))

from . import errors
from .errors import SimpleCADError
from ._native import *  # noqa: F401,F403
from ._native import __doc__  # noqa: F401
from ._native import _testing  # noqa: F401  (underscore names are not star-exported)
from ._native import _brep_region, _internal_mesh  # noqa: F401  (underscore names are not star-exported)
from ._native import _constrain_rsketch  # noqa: F401  (graph replay's generic constraint)
from ._native import _kernel_capabilities  # noqa: F401  (strategies the linked OCCT carries)
from ._native import _brep_region_path  # noqa: F401  (graph replay's locator check)
from ._native import _from_occt, _occt  # noqa: F401  (the OCCT classes of the kept Python layers; see occt/)
