import logging
from collections.abc import Generator
from typing import TYPE_CHECKING
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import HTTPException, status
from fastapi.params import Depends
from fastapi.security import OAuth2PasswordBearer
from redis import Redis
from sqlalchemy.orm import Session
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

logger = logging.getLogger(__name__)

from analytics.service import AnalyticService, AnalyticServiceInterface
from analytics.uow import UnitOfWorkAnalytics
from api.containers import Container
from auth.admin_service import AdminUserService
from auth.dtos import UserDTO
from auth.exceptions import AuthAccessInvalidTokenError
from auth.oauth_helper import OAuthHelper
from auth.repositories import (
    ConfirmationCodeRepositoryInterface,
    ConfirmationCodeRepositoryRedis,
    UserRepositoryInterface,
    UserRepositoryKeycloak,
)
from auth.services import AuthService, AuthServiceInterface
from quiz.services.family import FamilyService
from quiz.repositories.user_points import UserPointsRepository
from bank.service import BankService
from clients import (
    IdentityProviderClientInterface,
    IdentityProviderClientKeycloak,
    NotificationClientInterface,
)
from clients.apple.client import AppleOAuthClient
from clients.freedom_pay.settings import FreedomPaySettings
from clients.google.client import GoogleOAuthClient
from clients.notification.client import (
    NotificationClientEmail,
    NotificationClientSMS,
)
from common.enums import PlanType
from database import Database
from payments.services import PaymentService
from payments.ws_tokens import WebSocketTokenManager
from promocodes.service import PromocodeService
from quiz.parsers.question import QuestionParserXLSX
from quiz.services import (
    EntAttemptService,
    EntAttemptServiceInterface,
    EntOptionService,
    EntOptionServiceInterface,
    SubjectService,
    SubjectServiceInterface,
    TrainerAttemptService,
    TrainerAttemptServiceInterface,
)
from quiz.services._import import ImportService
from quiz.services.admin import AdminService
from quiz.services.attendance import AttendanceService
from quiz.services.cashback import CashbackService
from quiz.services.daily_tests import DailyTestService
from quiz.services.ent_questions import (
    EntOptionQuestionService,
    EntOptionQuestionServiceInterface,
)
from quiz.services.modules import ModuleLessonService, SubjectModuleService
from quiz.services.questions import QuestionService, QuestionServiceInterface
from quiz.services.statistic import StatisticService
from quiz.services.topics import TopicService, TopicServiceInterface
from quiz.services.trainers import TrainerService, TrainerServiceInterface
from quiz.uows.uows import UnitOfWorkQuestions, UnitOfWorkTests
from settings import Settings
from student.services import StudentService, StudentServiceInterface
from student.uows import UnitOfWorkStudents
from subscription.plan_repository import SubscriptionPlanRepository
from subscription.plan_service import SubscriptionPlanService
from subscription.service import SubscriptionService
from utils.cache import CacheService, CacheStrategy
from utils.file_service import FileService

if TYPE_CHECKING:
    from quiz.services.subject_combinations import SubjectCombinationService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login-swagger")


def get_settings() -> Settings:
    return Settings()  # noqa


@inject
def get_file_service(
    file_service: FileService = Depends(Provide[Container.file_service]),
) -> FileService:
    return file_service


def get_identity_provider_client_keycloak(settings: Settings = Depends(get_settings)):
    return IdentityProviderClientKeycloak(settings.keycloak)


def get_user_repository_keycloak(
    identity_provider_client: IdentityProviderClientInterface = Depends(
        get_identity_provider_client_keycloak
    ),
) -> UserRepositoryInterface:
    return UserRepositoryKeycloak(identity_provider_client)


def get_redis(settings: Settings = Depends(get_settings)):
    return Redis.from_url(settings.redis_url)


def get_confirmation_code_repository_redis(
    redis: Redis = Depends(get_redis),
) -> ConfirmationCodeRepositoryRedis:
    return ConfirmationCodeRepositoryRedis(redis)


@inject
def get_notification_client_telegram(
    telegram_client: NotificationClientInterface = Depends(
        Provide[Container.notification_client]
    ),
) -> NotificationClientInterface:
    return telegram_client


@inject
def get_notification_client_email(
    email_client: NotificationClientEmail = Depends(Provide[Container.email_client]),
) -> NotificationClientEmail:
    return email_client


@inject
def get_notification_client_sms(
    sms_client: NotificationClientSMS = Depends(Provide[Container.sms_client]),
) -> NotificationClientSMS:
    return sms_client


@inject
def get_notification_client_whatsapp(
    whatsapp_client=Depends(Provide[Container.whatsapp_client]),
):
    return whatsapp_client


@inject
def get_google_oauth_client(
    google_client=Depends(Provide[Container.google_oauth_client]),
):
    return google_client


@inject
def get_apple_oauth_client(apple_client=Depends(Provide[Container.apple_oauth_client])):
    return apple_client


@inject
def get_cache_service(
    cache_service: CacheService = Depends(Provide[Container.cache_service]),
) -> CacheService:
    return cache_service


def get_oauth_helper(
    users: UserRepositoryInterface = Depends(get_user_repository_keycloak),
    google_client: GoogleOAuthClient = Depends(get_google_oauth_client),
    apple_client: AppleOAuthClient = Depends(get_apple_oauth_client),
) -> OAuthHelper:
    return OAuthHelper(users, google_client, apple_client)


def get_auth_service(
    users: UserRepositoryInterface = Depends(get_user_repository_keycloak),
    confirmation_codes: ConfirmationCodeRepositoryInterface = Depends(
        get_confirmation_code_repository_redis
    ),
    notification_client: NotificationClientInterface = Depends(
        get_notification_client_telegram
    ),
    email_client: NotificationClientInterface = Depends(get_notification_client_email),
    sms_client: NotificationClientInterface = Depends(get_notification_client_sms),
    whatsapp_client: NotificationClientInterface = Depends(
        get_notification_client_whatsapp
    ),
    google_client: GoogleOAuthClient = Depends(get_google_oauth_client),
    apple_client: AppleOAuthClient = Depends(get_apple_oauth_client),
    oauth_helper: OAuthHelper = Depends(get_oauth_helper),
    identity_provider: IdentityProviderClientKeycloak = Depends(
        get_identity_provider_client_keycloak
    ),
) -> AuthServiceInterface:
    return AuthService(
        users,
        confirmation_codes,
        notification_client,
        email_client,
        sms_client,
        whatsapp_client,
        google_client,
        apple_client,
        oauth_helper,
        identity_provider,
    )


def get_database(settings: Settings = Depends(get_settings)) -> Database:
    return Database(settings.database)


def get_db_session(
    database: Database = Depends(get_database),
) -> Generator[Session]:
    session = database.session
    try:
        yield session
    finally:
        session.close()


@inject
def get_attendance_service(
    attendance_service: AttendanceService = Depends(
        Provide[Container.attendance_service]
    ),
) -> AttendanceService:
    return attendance_service


def get_subscription_plan_repository(
    db_session: Session = Depends(get_db_session),
) -> SubscriptionPlanRepository:
    return SubscriptionPlanRepository(db_session)


def get_subscription_plan_service(
    plan_repository: SubscriptionPlanRepository = Depends(
        get_subscription_plan_repository
    ),
) -> SubscriptionPlanService:
    return SubscriptionPlanService(plan_repository)


def get_subscription_service(
    auth_service: AuthServiceInterface = Depends(get_auth_service),
    database: Database = Depends(get_database),
) -> SubscriptionService:
    return SubscriptionService(auth_service, database)


# def get_user_with_subscription_check(
#     token: str = Depends(oauth2_scheme),
#     auth_service: AuthServiceInterface = Depends(get_auth_service),
#     subscription_service: SubscriptionService = Depends(get_subscription_service),
# ) -> UserDTO:
#     try:
#         user = auth_service.get_user_from_token(token)
#         user = subscription_service.refresh_subscription_status(user)
#         return user
#     except AuthAccessInvalidTokenError as e:
#         raise HTTPException(
#             status_code=HTTP_401_UNAUTHORIZED,
#             detail="Invalid authentication credentials",
#         ) from e


def get_user(
    token: str = Depends(oauth2_scheme),
    service: AuthServiceInterface = Depends(get_auth_service),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
    attendance_service: AttendanceService = Depends(get_attendance_service),
    db_session: Session = Depends(get_db_session),
    cache_service: CacheService = Depends(get_cache_service),
) -> UserDTO:
    try:
        user = service.get_user_from_token(token)
        # user = subscription_service.refresh_subscription_status(user)
        try:
            attendance_info = attendance_service.get_attendance_info(user.id)
            user.attendance_streak_days = attendance_info.streak.current_days
            user.attendance_total_points = attendance_info.streak.total_points
            user.attendance_today_points = attendance_info.streak.today_points
        except Exception:
            user.attendance_streak_days = 0
            user.attendance_total_points = 0
            user.attendance_today_points = None

        points_key = cache_service.make_key(
            CacheStrategy.USER, user_id=user.id, resource="user_points", params="total"
        )
        rank_key = cache_service.make_key(
            CacheStrategy.USER, user_id=user.id, resource="user_points", params="rank"
        )
        cached_points = cache_service.get(points_key)
        cached_rank = cache_service.get(rank_key)
        if cached_points is None or cached_rank is None:
            points_repo = UserPointsRepository(db_session)
            user.points = points_repo.get_total_points(user.id)
            user.rank = points_repo.get_user_rank(user.id)
            cache_service.set(points_key, user.points, ttl=60)
            cache_service.set(rank_key, user.rank, ttl=60)
        else:
            user.points = int(cached_points)
            user.rank = int(cached_rank)

        return user
    except AuthAccessInvalidTokenError as e:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        ) from e


def get_unit_of_work_tests(
    database: Database = Depends(get_database),
) -> UnitOfWorkTests:
    return UnitOfWorkTests(database)


def get_bank_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    cache_service: CacheService = Depends(get_cache_service),
) -> BankService:
    return BankService(uow, cache_service)


def get_cashback_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    cache_service: CacheService = Depends(get_cache_service),
    bank_service: BankService = Depends(get_bank_service),
) -> CashbackService:
    return CashbackService(uow, cache_service, bank_service)


def get_unit_of_work_analytics(
    database: Database = Depends(get_database),
) -> UnitOfWorkAnalytics:
    return UnitOfWorkAnalytics(database)


# def get_media_storage_client_minio(
#     settings: Settings = Depends(get_settings),
# ) -> MediaStorageClientInterface:
#     return MediaStorageClientMinio(settings.minio)


def get_module_lesson_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    cache_service: CacheService = Depends(get_cache_service),
) -> ModuleLessonService:
    """Зависимость для сервиса уроков модулей"""
    return ModuleLessonService(uow, cache_service)


def get_trainer_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    cache_service: CacheService = Depends(get_cache_service),
) -> TrainerServiceInterface:
    return TrainerService(uow, cache_service)


def get_trainer_attempt_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    cache_service: CacheService = Depends(get_cache_service),
    module_lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
    cashback_service: CashbackService = Depends(get_cashback_service),
) -> TrainerAttemptServiceInterface:
    return TrainerAttemptService(
        uow, cache_service, module_lesson_service, cashback_service
    )


def get_unit_of_work_students(
    database: Database = Depends(get_database),
) -> UnitOfWorkStudents:
    return UnitOfWorkStudents(database)


def get_student_service(
    uow: UnitOfWorkStudents = Depends(get_unit_of_work_students),
) -> StudentServiceInterface:
    return StudentService(uow)


def get_student(
    user: UserDTO = Depends(get_user),
    service: StudentServiceInterface = Depends(get_student_service),
):
    return service.get_or_create(user.id)


def get_subject_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    file_service: FileService = Depends(get_file_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> SubjectServiceInterface:
    return SubjectService(uow, file_service, cache_service)


def get_topic_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    cache_service: CacheService = Depends(get_cache_service),
) -> TopicServiceInterface:
    return TopicService(uow, cache_service)


def get_unit_of_work_questions(
    database: Database = Depends(get_database),
) -> UnitOfWorkQuestions:
    return UnitOfWorkQuestions(database)


def get_question_service(
    uow: UnitOfWorkQuestions = Depends(get_unit_of_work_questions),
    cache_service: CacheService = Depends(get_cache_service),
) -> QuestionServiceInterface:
    return QuestionService(uow, cache_service)


@inject
def get_question_parser(
    parser: QuestionParserXLSX = Depends(Provide[Container.question_parser]),
) -> QuestionParserXLSX:
    return parser


@inject
def get_ws_token_manager(
    ws_token_manager: WebSocketTokenManager = Depends(
        Provide[Container.ws_token_manager]
    ),
) -> WebSocketTokenManager:
    return ws_token_manager


def get_promocode_service(
    db_session: Session = Depends(get_db_session),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
) -> PromocodeService:
    return PromocodeService(db_session, subscription_service)


def get_payment_settings(
    settings: Settings = Depends(get_settings),
) -> FreedomPaySettings:
    return settings.freedom_pay


def get_payment_service(
    freedom_pay_settings: FreedomPaySettings = Depends(get_payment_settings),
    db_session: Session = Depends(get_db_session),
    user: UserDTO = Depends(get_user),
    auth_service: AuthServiceInterface = Depends(get_auth_service),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
    subscription_plan_service: SubscriptionPlanService = Depends(
        get_subscription_plan_service
    ),
) -> PaymentService:
    return PaymentService(
        freedom_pay_settings,
        db_session,
        user,
        auth_service,
        subscription_service,
        subscription_plan_service,
    )


async def allow_only_admins(
    access_token: str = Depends(oauth2_scheme),
    auth_service: AuthServiceInterface = Depends(get_auth_service),
):
    """Проверка прав администратора с использованием ролей из UserDTO"""
    try:
        user = auth_service.get_user_from_token(access_token)

        if not user.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User roles not loaded",
            )

        if "admin" not in user.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: only allowed for admins",
            )

        return user

    except AuthAccessInvalidTokenError as e:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Authentication system error in allow_only_admins: %s", e)
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail=f"Authentication system error: {type(e).__name__}: {e}",
        ) from e


def get_ent_options_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_questions),
    cache_service: CacheService = Depends(get_cache_service),
) -> EntOptionServiceInterface:
    return EntOptionService(uow, cache_service)


def get_ent_questions_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_questions),
    cache_service: CacheService = Depends(get_cache_service),
) -> EntOptionQuestionServiceInterface:
    return EntOptionQuestionService(uow, cache_service)


def get_ent_attempts_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    cache_service: CacheService = Depends(get_cache_service),
    cashback_service: CashbackService = Depends(get_cashback_service),
) -> EntAttemptServiceInterface:
    return EntAttemptService(uow, cache_service, cashback_service)


def get_import_service(
    question_service: QuestionServiceInterface = Depends(get_question_service),
    ent_option_service: EntOptionServiceInterface = Depends(get_ent_options_service),
    ent_question_service: EntOptionQuestionServiceInterface = Depends(
        get_ent_questions_service
    ),
    trainer_service: TrainerServiceInterface = Depends(get_trainer_service),
    topic_service: TopicServiceInterface = Depends(get_topic_service),
    subject_service: SubjectServiceInterface = Depends(get_subject_service),
    parser: QuestionParserXLSX = Depends(get_question_parser),
) -> ImportService:
    return ImportService(
        question_service=question_service,
        ent_option_service=ent_option_service,
        ent_question_service=ent_question_service,
        trainer_service=trainer_service,
        topic_service=topic_service,
        subject_service=subject_service,
        parser=parser,
    )


def get_analytics_service(
    uow: UnitOfWorkAnalytics = Depends(get_unit_of_work_analytics),
    users: UserRepositoryInterface = Depends(get_user_repository_keycloak),
) -> AnalyticServiceInterface:
    return AnalyticService(uow, users)


def get_admin_service(
    subject_service: SubjectServiceInterface = Depends(get_subject_service),
    topic_service: TopicServiceInterface = Depends(get_topic_service),
    trainer_service: TrainerServiceInterface = Depends(get_trainer_service),
    ent_option_service: EntOptionServiceInterface = Depends(get_ent_options_service),
    question_service: QuestionServiceInterface = Depends(get_question_service),
) -> AdminService:
    return AdminService(
        subject_service=subject_service,
        topic_service=topic_service,
        trainer_service=trainer_service,
        ent_option_service=ent_option_service,
        question_service=question_service,
    )


def get_subject_combination_service(
    session: Session = Depends(get_db_session),
    cache_service: CacheService = Depends(get_cache_service),
) -> "SubjectCombinationService":
    from quiz.services.subject_combinations import SubjectCombinationService

    return SubjectCombinationService(session, cache_service)


def get_progress_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    cache_service: CacheService = Depends(get_cache_service),
):
    from quiz.services.progress import ProgressService

    return ProgressService(uow, cache_service)


def require_subscription(
    required_plan: PlanType | None = None, allow_none: bool = False
):
    async def subscription_checker(
        user: UserDTO = Depends(get_user),
        subscription_service: SubscriptionService = Depends(get_subscription_service),
    ):
        status = await subscription_service.check_subscription_status(user)

        if not status["is_active"] and not allow_none:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Active subscription required to access this content",
            )

        if required_plan and not subscription_service.has_access(user, required_plan):
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail=f"'{required_plan.value}' plan or higher required. Your current plan is '{user.plan.value}'",
            )

        return user

    return subscription_checker


# def require_free_plan():
#     """Требует план FREE или выше"""
#     return require_subscription(required_plan=PlanType.FREE)


# def require_lite_plan():
#     """Требует план LITE или выше"""
#     return require_subscription(required_plan=PlanType.LITE)


# def require_pro_plan():
#     """Требует план PRO или выше"""
#     return require_subscription(required_plan=PlanType.PRO)


def require_active_subscription():
    """Требует любую активную подписку (кроме NONE)"""
    return require_subscription()


# def require_admin_access():
#     """Требует права администратора"""

#     async def admin_checker(
#         user: UserDTO = Depends(get_user),
#         auth_service: AuthServiceInterface = Depends(get_auth_service),
#     ):
#         if not auth_service.is_admin(user):
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Access denied: only allowed for admins",
#             )
#         return user

#     return admin_checker


# def require_admin_or_subscription(required_plan: PlanType | None = None):
#     """Требует либо права администратора, либо указанную подписку"""

#     async def checker(
#         user: UserDTO = Depends(get_user),
#         auth_service: AuthServiceInterface = Depends(get_auth_service),
#         subscription_service: SubscriptionService = Depends(get_subscription_service),
#     ):
#         if auth_service.is_admin(user):
#             return user

#         status = await subscription_service.check_subscription_status(user)

#         if not status["is_active"]:
#             raise HTTPException(
#                 status_code=HTTP_403_FORBIDDEN,
#                 detail="Active subscription required to access this content",
#             )

#         if required_plan and not subscription_service.has_access(user, required_plan):
#             raise HTTPException(
#                 status_code=HTTP_403_FORBIDDEN,
#                 detail=f"'{required_plan.value}' plan or higher required. Your current plan is '{user.plan.value}'",
#             )

#         return user

#     return checker


def get_statistic_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    analytic_service: AnalyticServiceInterface = Depends(get_analytics_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> StatisticService:
    return StatisticService(uow, analytic_service, cache_service)


def get_daily_test_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    cache_service: CacheService = Depends(get_cache_service),
    cashback_service: CashbackService = Depends(get_cashback_service),
    file_service: FileService = Depends(get_file_service),
) -> DailyTestService:
    return DailyTestService(uow, cache_service, cashback_service, file_service)


def get_current_user_id_optional(
    token: str | None = Depends(oauth2_scheme),
    auth_service: AuthServiceInterface = Depends(get_auth_service),
) -> UUID | None:
    """
    Получает user_id из токена, но не требует обязательной аутентификации.
    Возвращает None если токен невалиден или отсутствует.
    """
    if not token:
        return None
    try:
        user = auth_service.get_user_from_token(token)
        return user.id
    except AuthAccessInvalidTokenError:
        return None
    except Exception:
        return None


def get_subject_module_service(
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    cache_service: CacheService = Depends(get_cache_service),
) -> SubjectModuleService:
    """Зависимость для сервиса модулей предметов"""
    return SubjectModuleService(uow, cache_service)


def get_admin_user_service(
    identity_provider: IdentityProviderClientKeycloak = Depends(
        get_identity_provider_client_keycloak
    ),
) -> AdminUserService:
    return AdminUserService(identity_provider)


def get_family_service(
    session: Session = Depends(get_db_session),
    idp: IdentityProviderClientKeycloak = Depends(
        get_identity_provider_client_keycloak
    ),
) -> FamilyService:
    return FamilyService(session, idp)
