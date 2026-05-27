from .attendance import router as attendance_router
from .bank import router as bank_router
from .cashback import router as cashback_router
from .daily_tests import router as daily_tests_router
from .ents import router as ents_router
from .modules import router as modules_router
from .progress import router as progress_router
from .statistics import router as statistics_router
from .subjects import router as subjects_router
from .subscription import router as subscription_router
from .topics import router as topics_router
from .trainers import router as trainers_router
from .leaderboard import router as leaderboard_router
from .performance import router as performance_router
from .users import router as users_router
from .family import router as family_router
from .referrals import router as referrals_router

routers = [
    subjects_router,
    topics_router,
    trainers_router,
    ents_router,
    daily_tests_router,
    modules_router,
    attendance_router,
    statistics_router,
    progress_router,
    subscription_router,
    cashback_router,
    bank_router,
    leaderboard_router,
    performance_router,
    users_router,
    family_router,
    referrals_router,
]
