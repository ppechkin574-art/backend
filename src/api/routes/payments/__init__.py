from api.routes.payments.android import router as android_iap_router
from api.routes.payments.apple import router as apple_iap_router
from api.routes.payments.routes import router as payment_router
from api.routes.payments.webhook import router as payment_webhook_router
from api.routes.payments.websocket_routes import router as payment_ws_router

routers = [payment_router, payment_webhook_router, payment_ws_router, apple_iap_router, android_iap_router]
