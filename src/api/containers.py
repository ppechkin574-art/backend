from dependency_injector import containers, providers
from redis import Redis

from auth.oauth_helper import OAuthHelper
from auth.repositories import ConfirmationCodeRepositoryRedis, UserRepositoryKeycloak
from auth.services import AuthService
from clients import IdentityProviderClientKeycloak, NotificationClientTelegram
from clients.apple.client import AppleOAuthClient
from clients.firebase import FirebaseNotificationClient
from clients.google.client import GoogleOAuthClient
from clients.media_storage.client import MediaStorageClientMinio
from clients.notification.client import (
    NotificationClientEmail,
    NotificationClientSMS,
    # NotificationClientSMSTwilio,  # kept as code-level fallback, see sms_client provider below
    NotificationClientWhatsApp,
)
from clients.notification.telegram_otp_client import TelegramOtpClient
from database import Database
from payments.services import PaymentService
from payments.ws_tokens import WebSocketTokenManager
from quiz.parsers import QuestionParserXLSX
from quiz.services.attendance import AttendanceService
from quiz.services.daily_test_notifications import (
    DailyTestNotificationScheduler,
    DailyTestNotificationService,
)
from streak_bonus.reminder_service import (
    StreakReminderScheduler,
    StreakReminderService,
)
from quiz.services.modules import ModuleLessonService
from quiz.services.questions import QuestionService
from quiz.uows.uows import UnitOfWorkQuestions, UnitOfWorkTests
from settings import Settings
from subscription.service import SubscriptionService
from utils.cache import CacheService
from utils.file_service import FileService


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(packages=["api"])

    config = providers.Singleton(Settings)

    redis = providers.Singleton(Redis.from_url, url=config.provided.redis_url)
    database = providers.Singleton(Database, settings=config.provided.database)
    cache_service = providers.Singleton(
        CacheService,
        redis_client=redis,
        default_ttl=3600,
    )

    media_storage = providers.Singleton(
        MediaStorageClientMinio,
        settings=config.provided.minio,
    )

    file_service = providers.Singleton(
        FileService,
        media_storage=media_storage,
    )

    identity_provider_client = providers.Singleton(
        IdentityProviderClientKeycloak,
        keycloak_settings=config.provided.keycloak,
        cache_service=cache_service,
    )

    user_repository = providers.Singleton(
        UserRepositoryKeycloak,
        identity_provider_client=identity_provider_client,
        cache_service=cache_service,
    )

    confirmation_code_repository = providers.Singleton(
        ConfirmationCodeRepositoryRedis,
        redis=redis,
    )

    ws_token_manager = providers.Factory(WebSocketTokenManager, redis=redis, token_ttl=600)

    notification_client = providers.Singleton(
        NotificationClientTelegram,
        settings=config.provided.telegram_bot,
    )

    firebase_client = providers.Singleton(
        FirebaseNotificationClient,
        settings=config.provided.firebase,
    )

    email_client = providers.Singleton(NotificationClientEmail, email_settings=config.provided.email_client)

    # SMS via SMSC.kz — primary production provider. Cheapest per-SMS in KZ
    # (12-20 KZT). To switch to Twilio as primary (e.g. if SMSC delivery fails
    # on specific operators), swap the line below with the commented Twilio
    # provider and set TWILIO__* env vars.
    sms_client = providers.Singleton(NotificationClientSMS, smsc_settings=config.provided.smsc)
    # sms_client = providers.Singleton(NotificationClientSMSTwilio, twilio_settings=config.provided.twilio)

    whatsapp_client = providers.Singleton(
        NotificationClientWhatsApp,
        wazzup_settings=config.provided.wazzup,
        telegram_client=notification_client,
    )

    # Self-hosted Telegram OTP delivery — fallback after SMS for users on
    # broken operator routes (Beeline KZ pending registration). Disabled
    # when bot_token is empty; chain falls through to current behaviour.
    telegram_otp_client = providers.Singleton(
        TelegramOtpClient,
        settings=config.provided.telegram_otp,
    )

    google_oauth_client = providers.Singleton(
        GoogleOAuthClient,
        settings=config.provided.google_oauth,
    )

    apple_oauth_client = providers.Singleton(
        AppleOAuthClient,
        settings=config.provided.apple_oauth,
    )

    oauth_helper = providers.Singleton(
        OAuthHelper,
        google_client=google_oauth_client,
        apple_client=apple_oauth_client,
        users_repository=user_repository,
    )

    auth_service = providers.Singleton(
        AuthService,
        users=user_repository,
        confirmation_codes=confirmation_code_repository,
        notification_client=notification_client,
        email_client=email_client,
        sms_client=sms_client,
        whatsapp_client=whatsapp_client,
        telegram_otp_client=telegram_otp_client,
        redis=redis,
        google_client=google_oauth_client,
        apple_client=apple_oauth_client,
        oauth_helper=oauth_helper,
        identity_provider=identity_provider_client,
    )

    unit_of_work_tests = providers.Singleton(
        UnitOfWorkTests,
        db=database,
    )

    unit_of_work_questions = providers.Singleton(
        UnitOfWorkQuestions,
        db=database,
    )

    # media_storage = providers.Singleton(
    #     MediaStorageClientMinio,
    #     settings=config.provided.minio,
    # )

    question_service = providers.Singleton(QuestionService, uow=unit_of_work_questions, cache_service=cache_service)

    question_parser = providers.Singleton(QuestionParserXLSX)

    # unit_of_work_students = providers.Singleton(
    #     UnitOfWorkStudents,
    #     db=database,
    # )

    # student_service = providers.Singleton(
    #     StudentService,
    #     uow=unit_of_work_students,
    # )

    payment_service = providers.Singleton(PaymentService, payment_settings=config.provided.freedom_pay)

    daily_test_notification_service = providers.Singleton(
        DailyTestNotificationService,
        database=database,
        firebase_client=firebase_client,
        firebase_settings=config.provided.firebase,
    )

    daily_test_notification_scheduler = providers.Singleton(
        DailyTestNotificationScheduler,
        notification_service=daily_test_notification_service,
        firebase_settings=config.provided.firebase,
    )

    streak_reminder_service = providers.Singleton(
        StreakReminderService,
        database=database,
        firebase_client=firebase_client,
    )

    streak_reminder_scheduler = providers.Singleton(
        StreakReminderScheduler,
        database=database,
        reminder_service=streak_reminder_service,
    )

    subscription_service = providers.Singleton(
        SubscriptionService,
        auth_service=auth_service,
        database=database,
    )

    attendance_service = providers.Singleton(AttendanceService, uow=unit_of_work_tests, cache_service=cache_service)

    module_lesson_service = providers.Singleton(
        ModuleLessonService,
        uow=unit_of_work_tests,
        cache_service=cache_service,
    )
