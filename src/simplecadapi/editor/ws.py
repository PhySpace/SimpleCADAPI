"""WebSocket hub: connection registry and JSON broadcast.

The runtime (server-side, possibly from a worker thread) pushes messages;
every connected webui receives them. Delivery is fire-and-forget — the
webui is a viewport, not a durable consumer.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.websockets import WebSocket


class WsHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the running server loop so worker threads can push."""
        self._loop = loop

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    def broadcast(self, message: dict[str, Any]) -> None:
        """Push one JSON message to every connected client (thread-safe)."""
        self.broadcast_text(json.dumps(message, ensure_ascii=False))

    def broadcast_text(self, text: str) -> None:
        """Push one pre-serialized JSON frame to every client (thread-safe)."""
        self._push(text)

    def broadcast_bytes(self, data: bytes) -> None:
        """Push one binary frame to every client (thread-safe)."""
        self._push(data)

    def _push(self, frame: str | bytes) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._send_all(frame), loop)

    async def _send_all(self, frame: str | bytes) -> None:
        async with self._lock:
            clients = tuple(self._clients)
        for client in clients:
            try:
                if isinstance(frame, bytes):
                    await client.send_bytes(frame)
                else:
                    await client.send_text(frame)
            except Exception:
                self._clients.discard(client)


def preview_frame(envelope: dict[str, Any], data: bytes) -> bytes:
    """One binary frame carrying a ``preview`` envelope and the preview itself.

    ``<u32 big-endian N><N bytes of the envelope as UTF-8 JSON><the preview bytes (SCAPREV1 ...)>``.  The page gets
    the model with the event that announces it: no second request for it.
    """
    header = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
    return len(header).to_bytes(4, "big") + header + data
