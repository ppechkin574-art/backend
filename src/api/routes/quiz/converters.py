from datetime import UTC, date, datetime, time
from urllib.parse import urlparse

from api.routes.quiz.dtos import (
    EntAttemptAnswerRequestDTO,
    HintCreateRequestDTO,
    HintUpdateRequestDTO,
    QuestionCreateRequestDTO,
    QuestionListResponseDTO,
    QuestionUpdateRequestDTO,
    QuizAnswerRequestDTO,
    QuizCreateRequestDTO,
    StartAttemptRequestDTO,
    SubjectCreateRequestDTO,
    SubjectUpdateRequestDTO,
    SubjectWithQuestionsResponseDTO,
    TopicCreateRequestDTO,
    TopicUpdateRequestDTO,
    TopicWithQuestionsResponseDTO,
    VariantCreateRequestDTO,
    VariantUpdateRequestDTO,
)
from quiz.dtos.ent_answers import EntAttemptAnswerServiceDTO, EntQuestionServiceDTO
from quiz.dtos.ent_attempts import EntAttemptCreateServiceDTO
from quiz.dtos.ent_options import EntOptionsGetServiceDTO
from quiz.dtos.enums import Status
from quiz.dtos.hint import HintCreateServiceDTO, HintUpdateServiceDTO
from quiz.dtos.questions import (
    QuestionCreateServiceDTO,
    QuestionUpdateServiceDTO,
)
from quiz.dtos.statistic import EntStatisticGetServiceDTO, TopicStatisticGetServiceDTO
from quiz.dtos.subject import SubjectCreateServiceDTO, SubjectUpdateServiceDTO
from quiz.dtos.topic import TopicCreateServiceDTO, TopicUpdateServiceDTO
from quiz.dtos.trainer_attempt_answers import TestAnswerServiceDTO
from quiz.dtos.trainer_attempts import TrainerAttemptCreateServiceDTO
from quiz.dtos.variants import VariantCreateServiceDTO, VariantUpdateServiceDTO
from student.dtos import StudentDTO


def is_valid_image_path(url: str) -> bool:
    """Проверяет валидность URL изображения"""
    try:
        parsed = urlparse(url)
        return bool(parsed.scheme in ["http", "https"] and parsed.netloc)
    except Exception:
        return False


def to_test_answer_dto(
    student: StudentDTO, answer: QuizAnswerRequestDTO, test_attempt_question_id: int
) -> TestAnswerServiceDTO:
    return TestAnswerServiceDTO(
        student_guid=student.id,
        trainer_attempt_question_id=test_attempt_question_id,
        variants=answer.variants,
        spend_time=answer.spend_time,
    )


def to_test_create_dto(student: StudentDTO, params: QuizCreateRequestDTO) -> TrainerAttemptCreateServiceDTO:
    return TrainerAttemptCreateServiceDTO(
        student_guid=student.id,
        topic_id=params.topic_id,
        status=Status.in_progress,
    )


def to_subject_create_service(
    subject_create: SubjectCreateRequestDTO,
) -> SubjectCreateServiceDTO:
    return SubjectCreateServiceDTO(**subject_create.model_dump())


def to_subject_update_service(
    subject_update: SubjectUpdateRequestDTO,
) -> SubjectUpdateServiceDTO:
    return SubjectUpdateServiceDTO(**subject_update.model_dump())


def to_topic_create_service(
    topic_create: TopicCreateRequestDTO,
) -> TopicCreateServiceDTO:
    return TopicCreateServiceDTO(**topic_create.model_dump())


def to_topic_update_service(
    topic_update: TopicUpdateRequestDTO,
) -> TopicUpdateServiceDTO:
    return TopicUpdateServiceDTO(**topic_update.model_dump())


def to_hint_create_service(hint_create: HintCreateRequestDTO) -> HintCreateServiceDTO:
    return HintCreateServiceDTO(**hint_create.model_dump())


def to_variant_create_service(
    variant_create: VariantCreateRequestDTO,
) -> VariantCreateServiceDTO:
    return VariantCreateServiceDTO(**variant_create.model_dump())


def to_question_create_service(
    question_create: QuestionCreateRequestDTO,
) -> QuestionCreateServiceDTO:
    return QuestionCreateServiceDTO(
        subject_id=question_create.subject_id,
        topic_id=question_create.topic_id,
        difficulty=question_create.difficulty,
        type=question_create.type,
        blocks=question_create.blocks,
        hint=(to_hint_create_service(question_create.hint) if question_create.hint else None),
        variants=[to_variant_create_service(v) for v in question_create.variants],
    )


def to_hint_update_service(hint_update: HintUpdateRequestDTO) -> HintUpdateServiceDTO:
    return HintUpdateServiceDTO(**hint_update.model_dump())


def to_variant_update_service(
    variant_update: VariantUpdateRequestDTO,
) -> VariantUpdateServiceDTO:
    return VariantUpdateServiceDTO(**variant_update.model_dump())


def to_question_update_service(
    question_update: QuestionUpdateRequestDTO,
) -> QuestionUpdateServiceDTO:
    update_data = {}
    if question_update.subject_id is not None:
        update_data["subject_id"] = question_update.subject_id
    if question_update.topic_id is not None:
        update_data["topic_id"] = question_update.topic_id
    if question_update.difficulty is not None:
        update_data["difficulty"] = question_update.difficulty
    if question_update.type is not None:
        update_data["type"] = question_update.type
    if question_update.blocks is not None:
        update_data["blocks"] = question_update.blocks
    if question_update.hint is not None:
        update_data["hint"] = to_hint_update_service(question_update.hint)
    if question_update.variants is not None:
        update_data["variants"] = [to_variant_update_service(v) for v in question_update.variants]

    return QuestionUpdateServiceDTO(**update_data)


def to_topic_statistic_dto_service(
    topic_id: int, date_start: date, date_end: date, student: StudentDTO
) -> TopicStatisticGetServiceDTO:
    return TopicStatisticGetServiceDTO(
        topic_id=topic_id,
        student_guid=student.id,
        ts_start=int(datetime.combine(date_start, time.min).timestamp()),
        ts_end=int(datetime.combine(date_end, time.max).timestamp()),
    )


def to_ent_statistic_dto_service(date_start: date, date_end: date, student: StudentDTO) -> EntStatisticGetServiceDTO:
    return EntStatisticGetServiceDTO(
        student_guid=student.id,
        ts_start=int(datetime.combine(date_start, time.min).timestamp()),
        ts_end=int(datetime.combine(date_end, time.max).timestamp()),
    )


def to_ent_attempt_create_dto_service(
    start_attempt_params: StartAttemptRequestDTO, student: StudentDTO
) -> EntAttemptCreateServiceDTO:
    return EntAttemptCreateServiceDTO(
        student_guid=student.id,
        ent_option_id=start_attempt_params.ent_option_id,
        started_at=datetime.now(UTC),
        status=Status.in_progress,
    )


def to_ent_attempt_answer(answer: EntAttemptAnswerRequestDTO, student: StudentDTO) -> EntAttemptAnswerServiceDTO:
    return EntAttemptAnswerServiceDTO(
        student_guid=student.id,
        ent_attempt_id=answer.ent_attempt_id,
        questions=[EntQuestionServiceDTO(question_id=q.question_id, variants=q.variants) for q in answer.questions],
    )


def to_ent_options_get_service(subject_id: int | None, student: StudentDTO) -> EntOptionsGetServiceDTO:
    return EntOptionsGetServiceDTO(student_guid=student.id, subject_id=subject_id)


def to_question_list_response(questions: list, total_count: int) -> QuestionListResponseDTO:
    return QuestionListResponseDTO(data=questions, total_count=total_count, count=len(questions))


def to_subject_with_questions_response(subject, questions: list, total_count: int) -> SubjectWithQuestionsResponseDTO:
    return SubjectWithQuestionsResponseDTO(
        subject=subject,
        questions=QuestionListResponseDTO(data=questions, total_count=total_count, count=len(questions)),
    )


def to_topic_with_questions_response(topic, questions: list, total_count: int) -> TopicWithQuestionsResponseDTO:
    return TopicWithQuestionsResponseDTO(
        topic=topic,
        questions=QuestionListResponseDTO(data=questions, total_count=total_count, count=len(questions)),
    )
