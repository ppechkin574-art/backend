import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from sqlalchemy.orm import Session

from api.dependencies import (
    get_db_session,
    get_payment_service,
    get_ws_token_manager,
)
from api.routes.auth.routes import get_current_user
from auth.dtos.users import UserDTO
from payments.dtos import (
    CreatePaymentIn,
    CreatePaymentResponse,
    OrderDetailDTO,
    OrderHistoryItem,
    OrderListResponse,
    OrderSummaryDTO,
)
from payments.models import Payment, PaymentStatusHistory
from payments.services import PaymentService
from payments.ws_tokens import WebSocketTokenManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["User - Payments"])


@router.post("/create", response_model=CreatePaymentResponse)
async def api_create_payment(
    body: CreatePaymentIn,
    request: Request,
    payment_service: PaymentService = Depends(get_payment_service),
    ws_token_manager: WebSocketTokenManager = Depends(get_ws_token_manager),
):
    """
    Создаёт платеж у FreedomPay (init_payment) и возвращает redirect_url, order_id и websocket_url.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    payment = await payment_service.create_payment(
        amount=body.amount,
        user_ip=client_ip,
    )
    if payment.status == "failed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment creation failed")

    ws_token = ws_token_manager.create_ws_token(
        user_id=str(payment_service.user.id),
        order_id=payment.order_id,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    host = request.headers.get("host", "")

    if not host:
        base_url_str = str(request.base_url)
        if base_url_str.startswith("http://"):
            host = base_url_str[7:]
        elif base_url_str.startswith("https://"):
            host = base_url_str[8:]
        else:
            host = base_url_str

    if host.endswith(":80"):
        host = host[:-3]
    elif host.endswith(":443"):
        host = host[:-4]

    scheme = request.url.scheme
    ws_protocol = "wss" if scheme == "https" else "ws"

    websocket_url = f"{ws_protocol}://{host}/payments/ws/{payment.order_id}"

    logger.info("Payment created successfully: order_id=%s", payment.order_id)

    return CreatePaymentResponse(
        redirect_url=payment.pg_redirect_url,
        order_id=payment.order_id,
        websocket_url=websocket_url,
        ws_token=ws_token,
    )


@router.get("", response_model=OrderListResponse)
async def list_user_payments(
    session: Session = Depends(get_db_session),
    current_user: UserDTO = Depends(get_current_user),
):
    """
    Возвращает список платежей текущего пользователя.
    """
    payments = (
        session.query(Payment).filter(Payment.user_id == str(current_user.id)).order_by(Payment.created_at.desc()).all()
    )

    items = [
        OrderSummaryDTO(
            order_id=p.order_id,
            status=p.status,
            amount=p.amount,
            currency=p.currency,
            pg_payment_id=p.pg_payment_id,
            created_at=p.created_at,
        )
        for p in payments
    ]

    return OrderListResponse(results=len(items), data=items)


@router.get("/{order_id}", response_model=OrderDetailDTO)
async def get_payment_detail(
    order_id: str,
    session: Session = Depends(get_db_session),
    current_user: UserDTO = Depends(get_current_user),
):
    """
    Детали платежа
    """
    payment = session.query(Payment).filter(Payment.order_id == order_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if getattr(payment, "user_id", None) and str(payment.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    history_rows = (
        session.query(PaymentStatusHistory)
        .filter(PaymentStatusHistory.payment_id == payment.id)
        .order_by(PaymentStatusHistory.created_at.asc())
        .all()
    )
    history = [OrderHistoryItem(status=h.status, at=h.created_at) for h in history_rows]

    return OrderDetailDTO(
        order_id=payment.order_id,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        pg_payment_id=payment.pg_payment_id,
        pg_status_code=getattr(payment, "pg_status_code", None),
        pg_status_desc=getattr(payment, "pg_status_desc", None),
        pg_card_pan=getattr(payment, "pg_card_pan", None),
        pg_card_brand=getattr(payment, "pg_card_brand", None),
        pg_card_exp=getattr(payment, "pg_card_exp", None),
        pg_user_contact_email=getattr(payment, "pg_user_contact_email", None),
        pg_user_phone=getattr(payment, "pg_user_phone", None),
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        history=history,
    )


# async def authenticate_websocket(
#     token: str, auth_service: AuthServiceInterface
# ) -> UserDTO:
#     """
#     Аутентифицирует пользователя по токену для WebSocket соединения
#     """
#     if not token:
#         return None

#     try:
#         clean_token = token.replace("Bearer ", "").strip()
#         user = auth_service.get_user_from_token(clean_token)
#         return user

#     except AuthAccessInvalidTokenError:
#         return None
#     except Exception as e:
#         logger.exception(f"Auth error: {e}")
#         return None


# async def get_payment_by_order_id(order_id: str, session: Session) -> Payment:
#     """
#     Получает платеж по order_id
#     """
#     return session.query(Payment).filter(Payment.order_id == order_id).first()
