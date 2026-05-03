from enum import StrEnum


class PlanType(StrEnum):
    NONE = "NONE"
    FREE = "FREE"
    # LITE = "LITE"
    PRO = "PRO"
    # PREMIUM = "PREMIUM"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PENDING = "pending"


# class PromocodeType(StrEnum):
#     SUBSCRIPTION = "subscription"
#     DISCOUNT = "discount"
#     TRIAL = "trial"


class FeatureType(StrEnum):
    TOPIC_TRAINER = "topic_trainer"
    TRIAL_ENT = "trial_ent"
    FULL_COURSE = "full_course"
    CASHBACK = "cashback"
    DAILY_TASKS = "daily_tasks"
    AI = "ai"
    INCREASING_KEF = "increasing_kef"
    PARENT_ACCESS = "parent_access"
