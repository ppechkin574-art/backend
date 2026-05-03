from api.routes.payments.routes import router as payment_router
from api.routes.payments.websocket_routes import router as payment_ws_router

routers = [payment_router, payment_ws_router]
