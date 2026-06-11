import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from api.routes.payments.websocket.manager import manager
from payments.models import Payment, PaymentStatusHistory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["WebSocket"])


@router.websocket("/ws/{order_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    order_id: str,
):
    """
    WebSocket для получения обновлений статуса платежа в реальном времени.
    Требует одноразовый токен в query параметрах.
    """
    logger.info("WebSocket connection attempt for order: %s", order_id)

    token = websocket.query_params.get("token")

    if not token:
        logger.warning("No token provided")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        container = websocket.app.state.container

        ws_token_manager = container.ws_token_manager()

        token_data = ws_token_manager.verify_ws_token(token, order_id)

        if not token_data:
            logger.warning("Token verification failed")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        user_id = token_data["user_id"]
        token_order_id = token_data["order_id"]

        if token_order_id != order_id:
            logger.warning("Token order mismatch: %s != %s", token_order_id, order_id)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        database = container.database()
        session = database.session

        try:
            payment = session.query(Payment).filter(Payment.order_id == order_id).first()

            if not payment:
                logger.warning("Payment not found: %s", order_id)
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            if str(payment.user_id) != user_id:
                logger.warning("User %s has no access to order %s", user_id, order_id)
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            await websocket.accept()

            await manager.connect(websocket, order_id)
            logger.info("WebSocket connected for order: %s, user: %s", order_id, user_id)

            await websocket.send_json(
                {
                    "type": "connected",
                    "order_id": order_id,
                    "user_id": user_id,
                    "message": "WebSocket connection established",
                    "current_status": payment.status,
                    "timestamp": datetime.now(UTC).isoformat() + "Z",
                    "token_uses_left": token_data.get("max_uses", 10) - token_data.get("use_count", 0),
                }
            )

            history = (
                session.query(PaymentStatusHistory)
                .filter(PaymentStatusHistory.payment_id == payment.id)
                .order_by(PaymentStatusHistory.created_at.asc())
                .all()
            )

            if history:
                await websocket.send_json(
                    {
                        "type": "history",
                        "history": [
                            {
                                "status": h.status,
                                "at": h.created_at.isoformat() + "Z",
                                "id": h.id,
                            }
                            for h in history
                        ],
                    }
                )

            try:
                while True:
                    try:
                        data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                        if data == "ping":
                            await websocket.send_json(
                                {
                                    "type": "pong",
                                    "timestamp": datetime.now(UTC).isoformat() + "Z",
                                }
                            )
                            logger.debug("Pong sent for order: %s", order_id)

                        elif data.startswith("status"):
                            payment = session.query(Payment).filter(Payment.order_id == order_id).first()
                            await websocket.send_json(
                                {
                                    "type": "status",
                                    "status": payment.status if payment else "unknown",
                                    "order_id": order_id,
                                    "timestamp": datetime.now(UTC).isoformat() + "Z",
                                }
                            )

                        else:
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "message": "unknown_command",
                                }
                            )

                    except TimeoutError:
                        await websocket.send_json(
                            {
                                "type": "ping",
                                "timestamp": datetime.now(UTC).isoformat() + "Z",
                            }
                        )
                        continue

            except WebSocketDisconnect as e:
                logger.info("WebSocket disconnected for order: %s, code: %s", order_id, e.code)
                manager.disconnect(websocket, order_id)

        finally:
            session.close()

    except HTTPException as e:
        logger.warning("WebSocket auth failed: %s", str(e.detail))
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    except Exception as e:
        logger.exception("WebSocket error: %s", str(e))
        with contextlib.suppress(BaseException):
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
