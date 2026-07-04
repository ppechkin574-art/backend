from .admin import routers as admin_routers
from .analytics import routers as analytics_routers
from .auth.routes import routers as auth_routers
from .battle import battle_router
from .content import router as content_router
from .payments import routers as payments_routers
from .promocodes import router as promocodes_routers
from .system import routers as system_routers
from .user import routers as user_routers

routers = (
    auth_routers
    + user_routers
    + payments_routers
    + promocodes_routers
    + admin_routers
    + analytics_routers
    + system_routers
    + [content_router, battle_router]
)
