import sys
from pathlib import Path

# The tests run against the installed SDK: a wheel, an editable install, or the in-place development build (CMake writes
# the extension to src/simplecadapi/_cpp/).  Only when no compiled module is importable do they fall back to the checkout.
try:
    import simplecadapi._cpp  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# Make tests/python importable so `from ref import golden` works.
sys.path.insert(0, str(Path(__file__).parent))
