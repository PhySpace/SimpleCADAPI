"""PEP 517 build backend: scikit-build-core, plus the toolchain/OCCT detection a plain ``uv sync`` needs.

Why this exists: the package contains a C++ module (src/cpp) that needs a compiler, a build generator and an OpenCASCADE
install.  scikit-build-core leaves all three to CMake's defaults, and on a Windows machine without Visual Studio the default
is the NMake generator, which then fails ("'nmake' -? failed"), and nothing tells CMake where OCCT is.  Contributors had to
export CMAKE_GENERATOR / CC / CXX / CMAKE_ARGS by hand.  This wrapper does that detection itself and then delegates every hook
to scikit-build-core.  Anything the user already set (CMAKE_GENERATOR, CC, CXX, SCAD_OCCT_PREFIX, CMAKE_ARGS with a generator
or an OCCT prefix, CMAKE_BUILD_PARALLEL_LEVEL) is left alone, so CI (cibuildwheel) and Linux/macOS builds behave as before.

Detection runs only on Windows.  Linux and macOS use the system OCCT (or CI's) through CMake's own search.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

from scikit_build_core import build as _skbuild

# Everything scikit-build-core exposes (get_requires_for_*, prepare_metadata_*, build_sdist, ...) passes straight through.
from scikit_build_core.build import *  # noqa: F401,F403

REPO = Path(__file__).resolve().parents[2]
OCCT_TAG = "V7_9_3"  # tools/build_occt.py's DEFAULT_TAG: the kernel generation the SDK ships


def _log(msg: str) -> None:
    print(f"[scad_build] {msg}", file=sys.stderr, flush=True)


def _has_msvc() -> bool:
    """True when Visual Studio's C++ toolset is installed (CMake's Visual Studio generator finds it by itself)."""
    if shutil.which("cl"):
        return True
    pf = os.environ.get("ProgramFiles(x86)")
    vswhere = Path(pf, "Microsoft Visual Studio", "Installer", "vswhere.exe") if pf else None
    if vswhere and vswhere.is_file():
        out = subprocess.run(
            [str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        return bool(out)
    return False


def _total_memory_gb() -> float:
    class _Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total_phys", ctypes.c_ulonglong),
                    ("avail_phys", ctypes.c_ulonglong), ("total_page", ctypes.c_ulonglong),
                    ("avail_page", ctypes.c_ulonglong), ("total_virt", ctypes.c_ulonglong),
                    ("avail_virt", ctypes.c_ulonglong), ("avail_ext", ctypes.c_ulonglong)]

    status = _Status()
    status.length = ctypes.sizeof(_Status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
    return status.total_phys / 2**30


def _find_occt() -> Path | None:
    """An OCCT install prefix (the directory holding lib/cmake/opencascade), looked up in the usual places."""
    candidates = [os.environ.get("SCAD_OCCT_PREFIX"), "C:/occt", str(_occt_cache_dir())]
    for c in candidates:
        if c and (Path(c) / "lib" / "cmake" / "opencascade").is_dir():
            return Path(c)
    return None


def _occt_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "simplecadapi" / f"occt-{OCCT_TAG}"


def _build_occt(prefix: Path) -> None:
    _log(f"no OpenCASCADE found; building {OCCT_TAG} into {prefix} (one time, 20-40 minutes, cached for every later build)")
    subprocess.run([sys.executable, str(REPO / "src" / "cpp" / "tools" / "build_occt.py"), "--prefix", str(prefix), "--tag", OCCT_TAG], check=True)


def _prepare_windows_environment() -> None:
    env = os.environ
    cmake_args = env.get("CMAKE_ARGS", "")

    # 1. generator + compiler
    if not env.get("CMAKE_GENERATOR") and "-G" not in cmake_args and not _has_msvc():
        gxx, gcc, ninja = shutil.which("g++"), shutil.which("gcc"), shutil.which("ninja")
        if not (gxx and gcc):
            raise RuntimeError(
                "Building simplecadapi needs a C++ compiler on Windows: install Visual Studio Build Tools (C++ workload) "
                "or a MinGW-w64 gcc (e.g. `scoop install gcc`) and re-run."
            )
        # ninja is injected by scikit-build-core from the build requirements when the generator is Ninja
        env["CMAKE_GENERATOR"] = "Ninja"
        env.setdefault("CC", gcc)
        env.setdefault("CXX", gxx)
        _log(f"Visual Studio not found; using Ninja + {gxx}" + ("" if ninja else " (ninja from the build requirements)"))

    # 2. OpenCASCADE
    if "SCAD_OCCT_PREFIX" not in cmake_args:
        prefix = _find_occt()
        if prefix is None:
            prefix = _occt_cache_dir()
            _build_occt(prefix)
        # OpenCASCADE_DIR too: CMake's package registry may otherwise offer a stale OCCT left in %TEMP% by an old build
        cmake_args += f" -DSCAD_OCCT_PREFIX={prefix.as_posix()} -DOpenCASCADE_DIR={(prefix / 'lib' / 'cmake' / 'opencascade').as_posix()}"
        env["CMAKE_ARGS"] = cmake_args.strip()
        _log(f"OpenCASCADE: {prefix}")

    # 3. parallelism: one g++ translating OCCT-heavy bindings needs ~2 GB, so a many-core machine with little RAM ran out of
    # memory ("cc1plus: out of memory") under ninja's default of cpu_count + 2 jobs
    if not env.get("CMAKE_BUILD_PARALLEL_LEVEL"):
        jobs = max(1, min(os.cpu_count() or 2, int(_total_memory_gb() // 2.5)))
        env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(jobs)


def _prepare() -> None:
    if sys.platform == "win32":
        _prepare_windows_environment()


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    _prepare()
    return _skbuild.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    _prepare()
    return _skbuild.build_editable(wheel_directory, config_settings, metadata_directory)
