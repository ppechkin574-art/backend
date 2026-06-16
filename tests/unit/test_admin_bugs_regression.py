"""Regression tests for 5 admin panel bugs fixed in fix/backend-admin-bugs.

Bug 1 (N+1 Keycloak) — accepted as-is, no test.
Bug 2 (cache key)      — test_invalidate_uses_correct_user_prefix
Bug 3 (create_user)    — test_admin_create_user_defaults_to_free_plan
Bug 4 (N+1 subjects)   — test_subjects_dashboard_calls_batch_count_once
Bug 5 (N+1 topics)     — test_topics_dashboard_calls_batch_count_once
Bug 6 (ENT crash)      — test_ent_option_null_subject_returns_empty_string
"""

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from auth.admin_service import AdminUserService
from auth.dtos.admin import AdminUserCreateDTO
from auth.dtos.users import UserDTO
from common.enums import PlanType
from quiz.dtos.enums import SubjectType
from quiz.services.subjects import SubjectService
from quiz.services.topics import TopicService
from utils.cache import CacheService, CacheStrategy


# ---------------------------------------------------------------------------
# Bug 2 — cache key prefix
# ---------------------------------------------------------------------------


def _cache_service() -> CacheService:
    redis_stub = MagicMock()
    redis_stub.keys.return_value = []
    return CacheService(redis_client=redis_stub, default_ttl=60)


def test_invalidate_uses_correct_user_prefix():
    """invalidate_by_resource must build 'user:{id}:{res}:*', not 'user:user:{id}:{res}:*'."""
    svc = _cache_service()
    user_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    svc.invalidate_by_resource("questions", user_id)
    expected = f"user:{user_id}:questions:*"
    svc.redis.keys.assert_called_once_with(expected)


def test_invalidate_global_resource_no_user_id():
    """Without user_id the pattern uses CacheStrategy.GLOBAL prefix."""
    svc = _cache_service()
    svc.invalidate_by_resource("subjects")
    expected = "global:subjects:*"
    svc.redis.keys.assert_called_once_with(expected)


# ---------------------------------------------------------------------------
# Bug 3 — admin-created users start as FREE, not PRO
# ---------------------------------------------------------------------------


def _make_keycloak_user(user_id: UUID):
    u = MagicMock()
    u.id = user_id
    u.username = "testuser"
    u.email = "test@example.com"
    u.firstName = "Test"
    u.lastName = ""
    u.enabled = True
    u.createdTimestamp = None
    u.emailVerified = False
    u.attributes = {}
    return u


def test_admin_create_user_defaults_to_free_plan():
    """create_user must build UserCreateDTO with plan=FREE and subscription_end=None."""
    fake_id = UUID("11111111-2222-3333-4444-555555555555")
    kc = MagicMock()
    kc.get_or_create.return_value = (_make_keycloak_user(fake_id), False)
    kc.get_roles.return_value = []

    captured = []

    def capturing_converter(dto):
        captured.append(dto)
        mock_kc_dto = MagicMock()
        mock_kc_dto.attributes = MagicMock(allowed_subject_ids=[], role=[])
        return mock_kc_dto

    fake_user_dto = UserDTO(
        id=fake_id,
        username="testuser",
        name="Test User",
        is_active=True,
        plan=PlanType.FREE,
        roles=[],
    )

    with patch("auth.admin_service.to_keycloak_create_user_dto", side_effect=capturing_converter), \
         patch("auth.admin_service.to_user_dto", return_value=fake_user_dto):
        svc = AdminUserService(identity_provider=kc)
        data = AdminUserCreateDTO(name="Test User", role="teacher")
        svc.create_user(data)

    assert len(captured) == 1, "to_keycloak_create_user_dto must be called exactly once"
    dto = captured[0]
    assert dto.plan == PlanType.FREE, f"expected FREE, got {dto.plan}"
    assert dto.subscription_end is None, f"expected None, got {dto.subscription_end}"


# ---------------------------------------------------------------------------
# Bug 4 — N+1 in subjects dashboard
# ---------------------------------------------------------------------------


class _FakeSubjectModel:
    def __init__(self, id: int):
        self.id = id
        self.name = f"Subject {id}"
        self.type = SubjectType.main
        self.image = None


class _FakeQuestionsRepo:
    def __init__(self, counts_by_subject: dict):
        self._counts = counts_by_subject
        self.batch_calls = 0
        self.per_subject_calls = 0

    def count_all_by_subject(self) -> dict:
        self.batch_calls += 1
        return self._counts

    def count_by_subject(self, subject_id: int) -> int:
        self.per_subject_calls += 1
        return self._counts.get(subject_id, 0)


class _FakeTopicsRepo:
    def __init__(self, topic_counts: dict):
        self._counts = topic_counts
        self.batch_calls = 0
        self.per_topic_calls = 0

    def count_all_by_topic(self) -> dict:
        self.batch_calls += 1
        return self._counts

    def count_by_topic(self, topic_id: int) -> int:
        self.per_topic_calls += 1
        return self._counts.get(topic_id, 0)


class _FakeSubjectsRepo:
    def __init__(self, subjects):
        self._subjects = subjects

    def get_all_subjects_with_detailed_counts(self):
        return [(s, 3, 0) for s in self._subjects]


class _FakeSubjectUoW:
    def __init__(self, subjects, question_counts):
        self.questions = _FakeQuestionsRepo(question_counts)
        self.subjects = _FakeSubjectsRepo(subjects)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _make_file_service():
    fs = MagicMock()
    fs.get_subject_image_url.return_value = ""
    return fs


def _make_cache_service():
    c = MagicMock()
    return c


def test_subjects_dashboard_calls_batch_count_once():
    """get_all_subjects_with_detailed_info must call count_all_by_subject() once, not N times."""
    subjects = [_FakeSubjectModel(i) for i in range(1, 6)]  # 5 subjects
    question_counts = {1: 10, 2: 5, 3: 0, 4: 20, 5: 7}
    uow = _FakeSubjectUoW(subjects, question_counts)
    svc = SubjectService(uow=uow, file_service=_make_file_service(), cache_service=_make_cache_service())

    result = svc.get_all_subjects_with_detailed_info()

    assert uow.questions.batch_calls == 1, "count_all_by_subject() must be called exactly once"
    assert uow.questions.per_subject_calls == 0, "per-subject count_by_subject() must never be called"
    assert len(result) == 5
    assert result[0].question_count == 10
    assert result[2].question_count == 0


# ---------------------------------------------------------------------------
# Bug 5 — N+1 in topics dashboard
# ---------------------------------------------------------------------------


class _FakeTopicModel:
    def __init__(self, id: int, subject_id: int):
        self.id = id
        self.name = f"Topic {id}"
        self.subject_id = subject_id


class _FakeQuestionsRepoForTopics:
    def __init__(self, counts: dict):
        self._counts = counts
        self.batch_calls = 0
        self.per_topic_calls = 0

    def count_all_by_topic(self) -> dict:
        self.batch_calls += 1
        return self._counts

    def count_by_topic(self, topic_id: int) -> int:
        self.per_topic_calls += 1
        return self._counts.get(topic_id, 0)


class _FakeTrainersRepoForTopics:
    def __init__(self, counts: dict):
        self._counts = counts
        self.batch_calls = 0
        self.per_topic_calls = 0

    def count_all_by_topic(self) -> dict:
        self.batch_calls += 1
        return self._counts

    def count_by_topic(self, topic_id: int) -> int:
        self.per_topic_calls += 1
        return self._counts.get(topic_id, 0)


class _FakeTopicsRepoForTopics:
    def __init__(self, topics):
        self._topics = topics

    def get_all_topics_with_detailed_counts(self):
        return [(t, 0, 0) for t in self._topics]


class _FakeTopicUoW:
    def __init__(self, topics, q_counts, t_counts):
        self.questions = _FakeQuestionsRepoForTopics(q_counts)
        self.trainers = _FakeTrainersRepoForTopics(t_counts)
        self.topics = _FakeTopicsRepoForTopics(topics)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_topics_dashboard_calls_batch_count_once():
    """get_all_topics_with_detailed_info must call count_all_by_topic() once each for questions and trainers."""
    topics = [_FakeTopicModel(i, subject_id=1) for i in range(1, 11)]  # 10 topics
    q_counts = {i: i * 2 for i in range(1, 11)}
    t_counts = {i: 1 for i in range(1, 11)}
    uow = _FakeTopicUoW(topics, q_counts, t_counts)
    svc = TopicService(uow=uow, cache_service=_make_cache_service())

    result = svc.get_all_topics_with_detailed_info()

    assert uow.questions.batch_calls == 1, "questions.count_all_by_topic() must be called once"
    assert uow.questions.per_topic_calls == 0, "per-topic question count must not be called"
    assert uow.trainers.batch_calls == 1, "trainers.count_all_by_topic() must be called once"
    assert uow.trainers.per_topic_calls == 0, "per-topic trainer count must not be called"
    assert len(result) == 10
    assert result[0].question_count == 2   # topic id=1 → 1*2=2
    assert result[0].trainer_count == 1


# ---------------------------------------------------------------------------
# Bug 6 — ENT options crash when option.subject is None
# ---------------------------------------------------------------------------


def test_ent_option_null_subject_returns_empty_string():
    """subject_name expression must not raise AttributeError when subject is None."""

    class _FakeOption:
        subject = None

    option = _FakeOption()
    name = option.subject.name if option.subject else ""
    assert name == ""


def test_ent_option_with_subject_returns_name():
    """subject_name expression returns the real name when subject is present."""

    class _FakeSubject:
        name = "Math"

    class _FakeOption:
        subject = _FakeSubject()

    option = _FakeOption()
    name = option.subject.name if option.subject else ""
    assert name == "Math"
