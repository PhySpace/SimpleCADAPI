"""Strict JSON parsing and RFC 8785 canonicalization for Scene 1.0."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

import rfc8785

from ..errors import SimpleCADMessageError


MAX_SAFE_INTEGER = 9_007_199_254_740_991


class DuplicateKeyError(SimpleCADMessageError):
    """Raised before object construction when JSON contains a duplicate key."""

    operation = "scene_canonical_json"


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON object member: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {token}")


def _reject_unpaired_surrogates(value: Any) -> Any:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            try:
                current.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("string contains an unpaired surrogate") from exc
        elif isinstance(current, dict):
            stack.extend(current.keys())
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return value


def _jcs_int(token: str) -> int | float:
    # JCS numbers are doubles, and integral doubles below 1e21 print without an exponent
    # (a slab's inertia 1.18e19 -> "11773562012270215000"): read such tokens back as that double.
    value = int(token)
    return float(value) if abs(value) > MAX_SAFE_INTEGER else value


def parse_strict_json(data: bytes | bytearray | memoryview | str, *, _jcs_numbers: bool = False) -> Any:
    """Parse one strict UTF-8 JSON value while rejecting duplicate keys.

    BOMs, invalid UTF-8, comments, non-finite numbers, and trailing tokens are
    rejected.  The returned value is not normalized.
    """

    if isinstance(data, str):
        text = data
        if text.startswith("\ufeff"):
            raise ValueError("UTF-8 BOM is forbidden")
    else:
        raw = bytes(data)
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ValueError("UTF-8 BOM is forbidden")
        text = raw.decode("utf-8", errors="strict")
    try:
        return _reject_unpaired_surrogates(
            json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_nonfinite,
                parse_int=_jcs_int if _jcs_numbers else None,
            )
        )
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds parser capacity") from exc


def canonical_json_bytes(value: Any) -> bytes:
    """Return RFC 8785 JCS bytes, rejecting values outside the JCS domain."""

    try:
        return rfc8785.dumps(value)
    except rfc8785.CanonicalizationError as exc:
        raise ValueError(str(exc)) from exc


def parse_canonical_json(data: bytes | bytearray | memoryview | str) -> Any:
    """Parse JSON and require the input bytes to already be exact JCS bytes."""

    if isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raw = bytes(data)
    value = parse_strict_json(raw, _jcs_numbers=True)
    canonical = canonical_json_bytes(value)
    if raw != canonical:
        raise ValueError("JSON bytes are not RFC 8785 canonical")
    return value


def canonical_json_hash(value: Any) -> str:
    """Return a lowercase Scene content hash over canonical JSON bytes."""

    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def compute_scene_revision(scene: Mapping[str, Any]) -> str:
    """Compute the two-pass Scene revision with the top-level field omitted."""

    draft = dict(scene)
    draft.pop("revision", None)
    return canonical_json_hash(draft)


def with_scene_revision(scene: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep copy carrying its computed Scene revision."""

    result = deepcopy(dict(scene))
    result["revision"] = compute_scene_revision(result)
    return result
