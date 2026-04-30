from api.routes.analytics.admin_routes import router as analytics_admin_router
from api.routes.analytics.public_routes import router as analytics_user_router

routers = [analytics_admin_router, analytics_user_router]
