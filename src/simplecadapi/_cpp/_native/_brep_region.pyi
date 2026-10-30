"""
simplecadapi._internal.brep_region
"""
from __future__ import annotations
import pathlib
import typing
__all__: list[str] = ['MAGIC', 'MAJOR_VERSION', 'MINOR_VERSION', 'checked_region_path', 'copy_step_region_rpath', 'decode_artifact', 'default_ocp_version', 'read_artifact', 'region_profile']
def checked_region_path(path: str, for_graph: bool) -> str:
    ...
def copy_step_region_rpath(path: os.PathLike | str | bytes, output_path: os.PathLike | str | bytes, *, ocp_version: str | None = None) -> pathlib.Path:
    """
    Copy one STEP solid into a .scadbrep snapshot (the whole-solid form of the Python function).
    """
def decode_artifact(data: bytes, *, expected_root_kind: str | None = None) -> tuple[typing.Any, typing.Any]:
    ...
def default_ocp_version() -> str:
    ...
def read_artifact(path: os.PathLike | str | bytes, sha256: str, *, expected_root_kind: str, replay_root: os.PathLike | str | bytes | None = None) -> tuple[typing.Any, typing.Any, str]:
    """
    (shape, manifest, sha256) of a hash-pinned .scadbrep file.
    """
def region_profile(ocp_version: str) -> str:
    ...
MAGIC: bytes  # value = b'SCADBREP'
MAJOR_VERSION: int = 1
MINOR_VERSION: int = 0
