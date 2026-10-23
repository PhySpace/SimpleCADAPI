#!/usr/bin/env python3
"""Build OpenCASCADE from source as static libraries, the same way on every platform.

    python tools/build_occt.py --prefix /opt/occt [--tag V7_9_3] [--jobs N] [--work DIR]

The result is what `-DSCAD_OCCT_PREFIX=<prefix>` expects (it holds lib/cmake/opencascade).
Only the modules scad uses are built; visualization/Draw are off. Release wheels use this so
the kernel version is identical on Windows, macOS and Linux (x86_64 and aarch64), and so the
extension carries its own OCCT instead of depending on a system install.

Standard library only (runs inside manylinux, a macOS runner, or a Windows runner).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_TAG = "V7_9_3"
URL = "https://github.com/Open-Cascade-SAS/OCCT/archive/refs/tags/{tag}.tar.gz"


def download(url: str, dest: Path, attempts: int = 6) -> None:
    """urlretrieve with retries: CI runners and VMs drop connections now and then."""
    import time

    for attempt in range(1, attempts + 1):
        try:
            partial = dest.with_suffix(dest.suffix + ".part")
            urllib.request.urlretrieve(url, partial)
            with tarfile.open(partial):  # reject a truncated download before keeping it
                pass
            partial.replace(dest)
            return
        except (OSError, tarfile.TarError) as error:
            print(f"download attempt {attempt}/{attempts} failed: {error}", flush=True)
            if attempt == attempts:
                raise
            time.sleep(min(30, 2 ** attempt))


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prefix", required=True, type=Path)
    ap.add_argument("--tag", default=DEFAULT_TAG)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--work", type=Path, default=None, help="scratch directory (default: temp)")
    ap.add_argument("--source", type=Path, default=None, help="use this OCCT source tree instead of downloading")
    ap.add_argument("--force", action="store_true", help="rebuild even if the prefix already has OCCT")
    args = ap.parse_args()

    prefix = args.prefix.resolve()
    marker = prefix / "lib" / "cmake" / "opencascade"
    if marker.exists() and not args.force:
        print(f"OCCT already installed in {prefix}; use --force to rebuild")
        return 0

    work = (args.work or Path(tempfile.mkdtemp(prefix="occt-build-"))).resolve()
    work.mkdir(parents=True, exist_ok=True)

    if args.source:
        src = args.source.resolve()
    else:
        tarball = work / f"{args.tag}.tar.gz"
        if not tarball.exists():
            print(f"downloading {URL.format(tag=args.tag)}", flush=True)
            download(URL.format(tag=args.tag), tarball)
        with tarfile.open(tarball) as tar:
            top = tar.getnames()[0].split("/")[0]
            if not (work / top).exists():
                tar.extractall(work)
        src = work / top

    build = work / "build"
    build.mkdir(exist_ok=True)

    options = {
        "CMAKE_BUILD_TYPE": "Release",
        "CMAKE_INSTALL_PREFIX": str(prefix),
        "CMAKE_POSITION_INDEPENDENT_CODE": "ON",
        "BUILD_LIBRARY_TYPE": "Static",
        "BUILD_MODULE_FoundationClasses": "ON",
        "BUILD_MODULE_ModelingData": "ON",
        "BUILD_MODULE_ModelingAlgorithms": "ON",
        "BUILD_MODULE_DataExchange": "ON",
        "BUILD_MODULE_ApplicationFramework": "ON",
        # TKXCAF (STEP assemblies) links TKService/TKV3d; the viewer back-ends are not needed.
        "BUILD_MODULE_Visualization": "ON",
        "BUILD_MODULE_Draw": "OFF",
        "BUILD_DOC_Overview": "OFF",
        "USE_OPENGL": "OFF",
        "USE_GLES2": "OFF",
        "USE_D3D": "OFF",
        "USE_TK": "OFF",
        "USE_XLIB": "OFF",
        "USE_FREETYPE": "OFF",
        "USE_FREEIMAGE": "OFF",
        "USE_RAPIDJSON": "OFF",
        "USE_TBB": "OFF",
        "USE_VTK": "OFF",
        "USE_OPENVR": "OFF",
        "USE_FFMPEG": "OFF",
        "USE_DRACO": "OFF",
        "USE_TCL": "OFF",
        # Keep range/construction checks as exceptions (scad::occt_guard turns them into
        # KernelError) instead of undefined behaviour.
        "BUILD_RELEASE_DISABLE_EXCEPTIONS": "OFF",
        "INSTALL_DIR_LAYOUT": "Unix",
    }
    cmd = ["cmake", "-S", str(src), "-B", str(build)]
    # Ninja where a compiler is already on the path (Linux, macOS).  On Windows only when the MSVC environment is active
    # (`cl` on the path: the release workflow activates it); otherwise the default Visual Studio generator finds MSVC by
    # itself, which a bare Ninja would not.
    ninja = shutil.which("ninja") is not None and (sys.platform != "win32" or shutil.which("cl") is not None)
    if ninja:
        cmd += ["-G", "Ninja"]
    cmd += [f"-D{k}={v}" for k, v in options.items()]
    if sys.platform == "darwin" and os.environ.get("MACOSX_DEPLOYMENT_TARGET"):
        cmd.append(f"-DCMAKE_OSX_DEPLOYMENT_TARGET={os.environ['MACOSX_DEPLOYMENT_TARGET']}")
    run(cmd)
    build_cmd = ["cmake", "--build", str(build), "--target", "install", "--parallel", str(args.jobs)]
    if not ninja:  # a multi-config generator (Visual Studio) takes the configuration at build time
        build_cmd += ["--config", "Release"]
    run(build_cmd)
    print(f"OCCT {args.tag} installed to {prefix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
