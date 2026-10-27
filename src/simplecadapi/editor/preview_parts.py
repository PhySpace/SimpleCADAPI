"""The editor's store of preview parts, and the previews built from it.

A model preview is the same parts most of the time: a joint angle moves nodes, an edit rebuilds one link.  Parts are
identified by the content of their geometry, so the kernel posts only the parts the server does not have yet and the
server hands each page only the parts that page does not have (see :func:`simplecadapi.scene.preview.encode_preview`).

The store keeps each part as its header entry plus its raw arrays.  :meth:`PartStore.assemble` builds a preview from it
for the keys it is given, so the server can make the full preview (a page that joins late, ``/api/preview/latest``, the
model kept on disk) and the delta for a page that already has some parts.
"""

from __future__ import annotations

import json
import struct
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Collection, Iterable

from ..scene.preview import MAGIC, PREVIEW_SCHEMA, PreviewError

_ARRAYS = ("positions", "normals", "indices", "edge_positions", "edge_indices", "vertex_positions")
_ITEM = 4  # every array is little-endian float32 or uint32
_MAX_BYTES = 512 << 20


@dataclass(frozen=True)
class Stored:
    meta: dict[str, Any]
    """The part's header entry; array offsets are relative to ``data``."""
    data: bytes


@dataclass(frozen=True)
class ParsedPreview:
    """A preview split into its nodes and the parts it carries."""

    nodes: list[dict[str, Any]]
    parts: dict[str, Stored]

    @property
    def needed(self) -> set[str]:
        """The keys of the parts the nodes draw."""
        return {node["part"] for node in self.nodes}


def parse_preview(data: bytes) -> ParsedPreview:
    """Split an encoded preview (full or with parts omitted) into nodes and per-part blocks."""

    if not data.startswith(MAGIC):
        raise PreviewError("not a preview")
    (length,) = struct.unpack_from("<I", data, len(MAGIC))
    start = len(MAGIC) + 8
    header = json.loads(data[start : start + length])
    if header.get("schema") != PREVIEW_SCHEMA:
        raise PreviewError(f"unsupported preview schema: {header.get('schema')!r}")
    base = start + length
    parts: dict[str, Stored] = {}
    for part in header["parts"]:
        first = part["positions"]["offset"]
        last = part["vertex_positions"]
        end = last["offset"] + last["count"] * _ITEM
        meta = dict(part)
        for name in _ARRAYS:
            meta[name] = {"offset": part[name]["offset"] - first, "count": part[name]["count"]}
        parts[part["key"]] = Stored(meta, bytes(data[base + first : base + end]))
    return ParsedPreview(list(header["nodes"]), parts)


class PartStore:
    """Preview parts by key, least recently used out first (the parts of the latest scene are never dropped)."""

    def __init__(self, max_bytes: int = _MAX_BYTES) -> None:
        self._parts: OrderedDict[str, Stored] = OrderedDict()
        self._bytes = 0
        self._max = max_bytes
        self._lock = threading.RLock()

    def __contains__(self, key: str) -> bool:
        return key in self._parts

    def __len__(self) -> int:
        return len(self._parts)

    def missing(self, keys: Iterable[str]) -> set[str]:
        with self._lock:
            return {key for key in keys if key not in self._parts}

    def put(self, parts: dict[str, Stored], *, keep: Collection[str] = ()) -> None:
        with self._lock:
            self._put(parts, keep)

    def _put(self, parts: dict[str, Stored], keep: Collection[str]) -> None:
        for key, stored in parts.items():
            old = self._parts.pop(key, None)
            if old is not None:
                self._bytes -= len(old.data)
            self._parts[key] = stored
            self._bytes += len(stored.data)
        protected = set(keep) | set(parts)
        for key in list(self._parts):
            if self._bytes <= self._max:
                break
            if key not in protected:
                self._bytes -= len(self._parts.pop(key).data)

    def touch(self, keys: Iterable[str]) -> None:
        with self._lock:
            for key in keys:
                if key in self._parts:
                    self._parts.move_to_end(key)

    def assemble(self, nodes: list[dict[str, Any]], omit: Collection[str] = ()) -> bytes:
        """The preview of *nodes*; the parts in *omit* are left out (the reader has them)."""

        with self._lock:
            return self._assemble(nodes, omit)

    def _assemble(self, nodes: list[dict[str, Any]], omit: Collection[str]) -> bytes:
        wanted: list[str] = []
        for node in nodes:
            key = node["part"]
            if key not in omit and key not in wanted:
                wanted.append(key)
        entries: list[dict[str, Any]] = []
        chunks: list[bytes] = []
        cursor = 0
        for key in wanted:
            stored = self._parts[key]
            meta = dict(stored.meta)
            for name in _ARRAYS:
                meta[name] = {"offset": cursor + stored.meta[name]["offset"], "count": stored.meta[name]["count"]}
            entries.append(meta)
            chunks.append(stored.data)
            cursor += len(stored.data)
        encoded = json.dumps({"schema": PREVIEW_SCHEMA, "parts": entries, "nodes": nodes}, separators=(",", ":")).encode("utf-8")
        encoded += b" " * (-len(encoded) % 8)
        return MAGIC + struct.pack("<I", len(encoded)) + b"\0\0\0\0" + encoded + b"".join(chunks)
