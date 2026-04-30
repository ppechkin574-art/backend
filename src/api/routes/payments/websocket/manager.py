import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
        self._heartbeat_task = None
        self._stop_heartbeat = False

    async def connect(self, websocket: WebSocket, order_id: str):
        if order_id not in self.active_connections:
            self.active_connections[order_id] = []
        self.active_connections[order_id].append(websocket)

        await websocket.send_json(
            {
                "type": "connected",
                "order_id": order_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def disconnect(self, websocket: WebSocket, order_id: str):
        if order_id in self.active_connections:
            self.active_connections[order_id].remove(websocket)
            if not self.active_connections[order_id]:
                del self.active_connections[order_id]

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast_to_order(self, message: dict, order_id: str):
        """Отправляем сообщение всем подключенным клиентам по order_id"""
        if order_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[order_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.exception("WebSocket send error: %s", str(e))
                    disconnected.append(connection)

            for connection in disconnected:
                self.disconnect(connection, order_id)

    async def start_heartbeat(self):
        """Запускает heartbeat в фоне"""
        if self._heartbeat_task is None:
            self._stop_heartbeat = False
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("WebSocket heartbeat started")

    async def _heartbeat_loop(self):
        """Периодическая отправка heartbeat"""
        while not self._stop_heartbeat:
            try:
                await asyncio.sleep(30)
                if self._stop_heartbeat:
                    break

                current_time = datetime.now(UTC)
                for order_id, connections in list(self.active_connections.items()):
                    disconnected = []
                    for connection in connections:
                        try:
                            await connection.send_json(
                                {
                                    "type": "heartbeat",
                                    "timestamp": current_time.isoformat(),
                                }
                            )
                        except Exception:
                            disconnected.append(connection)

                    for connection in disconnected:
                        self.disconnect(connection, order_id)
            except Exception as e:
                logger.exception("Heartbeat error: %s", str(e))

    async def stop_heartbeat(self):
        """Останавливает heartbeat"""
        self._stop_heartbeat = True
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None


manager = ConnectionManager()
