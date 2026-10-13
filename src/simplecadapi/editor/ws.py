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
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._send_all(text), loop)

    async def _send_all(self, text: str) -> None:
        async with self._lock:
            clients = tuple(self._clients)
        for client in clients:
            try:
                await client.send_text(text)
            except Exception:
                self._clients.discard(client)
