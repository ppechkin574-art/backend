from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class BattleConnectionManager:
    """Manages WebSocket connections per battle session.

    Layout: { session_id: { player_id: WebSocket } }
    """

    def __init__(self):
        self._sessions: dict[str, dict[str, WebSocket]] = {}

    async def connect(self, session_id: str, player_id: str, ws: WebSocket) -> None:
        await ws.accept()
        if session_id not in self._sessions:
            self._sessions[session_id] = {}
        self._sessions[session_id][player_id] = ws
        logger.info("Battle WS connected: session=%s player=%s", session_id, player_id[:8])

    def disconnect(self, session_id: str, player_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].pop(player_id, None)
            if not self._sessions[session_id]:
                del self._sessions[session_id]
        logger.info("Battle WS disconnected: session=%s player=%s", session_id, player_id[:8])

    async def send_to(self, session_id: str, player_id: str, message: dict) -> None:
        ws = self._sessions.get(session_id, {}).get(player_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                logger.warning("Send failed: session=%s player=%s", session_id, player_id[:8])

    async def broadcast_session(self, session_id: str, message: dict) -> None:
        for player_id, ws in list(self._sessions.get(session_id, {}).items()):
            try:
                await ws.send_json(message)
            except Exception:
                logger.warning("Broadcast failed: session=%s player=%s", session_id, player_id[:8])

    def is_connected(self, session_id: str, player_id: str) -> bool:
        return player_id in self._sessions.get(session_id, {})

    def get_opponent_id(self, session_id: str, my_id: str) -> str | None:
        players = self._sessions.get(session_id, {})
        for pid in players:
            if pid != my_id:
                return pid
        return None


battle_manager = BattleConnectionManager()
