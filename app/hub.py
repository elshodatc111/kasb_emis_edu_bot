from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)


class Hub:
    """Veb-panelga ulangan brauzerlarga jonli hodisalarni (yangi xabar va h.k.) yuboradi."""

    def __init__(self) -> None:
        self._clients: set[Any] = set()
        self._lock = asyncio.Lock()

    async def register(self, ws: Any) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def unregister(self, ws: Any) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, event: dict) -> None:
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            await self.unregister(ws)

    @property
    def count(self) -> int:
        return len(self._clients)
