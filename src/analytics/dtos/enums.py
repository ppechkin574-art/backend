from enum import Enum


class UserActivityEnum(Enum):
    app_first_open = "app_first_open"
    app_opened = "app_opened"
    app_closed = "app_closed"
    app_crashed = "app_crashed"
    app_backgrounded = "app_backgrounded"
    user_registered = "user_registered"
    user_logged_in = "user_logged_in"
    user_logged_out = "user_logged_out"
    user_reset_password = "user_reset_password"  # noqa S105
    trainer_started = "trainer_started"
    trainer_answer = "trainer_answer"
    trainer_completed = "trainer_completed"
    ent_subject_started = "ent_subject_started"
    ent_subject_completed = "ent_subject_completed"
    ent_full_started = "ent_full_started"
    ent_full_completed = "ent_full_completed"
    daily_test_started = "daily_test_started"
    daily_test_completed = "daily_test_completed"
    purchase_initiated = "purchase_initiated"
    purchase_success = "purchase_success"
    purchase_failed = "purchase_failed"


class MistakeCategory(Enum):
    low = "low"
    medium = "medium"
    hard = "hard"
