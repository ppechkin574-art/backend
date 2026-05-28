from .app_settings import router as app_settings_router
from .bank import router as bank_router
from .leaderboard_prizes import router as leaderboard_prizes_router
from .streak_push_template import router as streak_push_template_router
from .streak_reward_tiers import router as streak_reward_tiers_router
from .cache import router as cache_router
from .content import router as content_router
from .dashboard import router as dashboard_router
from .ents import router as ents_router
from .modules import router as modules_router
from .notifications import router as notifications_router
from .notifications_send import router as notifications_send_router
from .promocodes import router as promocodes_router
from .questions import router as questions_router
from .statistics import router as statistics_router
from .subject_combinations import router as subject_combinations_router
from .subjects import router as subjects_router
from .subscription import router as subscription_router
from .topics import router as topics_router
from .trainers import router as trainers_router
from .users import router as users_router

routers = [
    dashboard_router,
    subjects_router,
    topics_router,
    questions_router,
    ents_router,
    trainers_router,
    statistics_router,
    notifications_router,
    notifications_send_router,
    subject_combinations_router,
    promocodes_router,
    modules_router,
    users_router,
    bank_router,
    cache_router,
    subscription_router,
    content_router,
    app_settings_router,
    leaderboard_prizes_router,
    streak_reward_tiers_router,
    streak_push_template_router,
]
