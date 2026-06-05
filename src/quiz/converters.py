from datetime import UTC, datetime

# from uuid import UUID
from quiz.dtos import (
    HintCreateRepositoryDTO,
    # HintRepositoryDTO,
    SubjectCreateRepositoryDTO,
    SubjectRepositoryDTO,
    TopicCreateRepositoryDTO,
    TopicRepositoryDTO,
)

# from quiz.dtos.daily_tests import (
#     DailyTestDeviceTokenDTO,
#     DailyTestHistoryItemDTO,
#     DailyTestResultDTO,
#     SubjectPreferenceDTO,
# )
from quiz.dtos.ent_attempts import (
    EntAttemptCreateRepositoryDTO,
    EntAttemptCreateServiceDTO,
    # EntAttemptOptionStatisticRepositoryDTO,
    # EntAttemptOptionStatisticServiceDTO,
    EntAttemptRepositoryDTO,
    EntAttemptServiceDTO,
)
from quiz.dtos.ent_options import (
    # EntOptionCreateDTO,
    # EntOptionCreateServiceDTO,
    EntOptionsGetRepositoryDTO,
    EntOptionsGetServiceDTO,
    # EntOptionUpdateServiceDTO,
)
from quiz.dtos.enums import (
    # Difficulty, QuestionType,
    Status,
)
from quiz.dtos.hint import (
    HintCreateServiceDTO,
    HintServiceDTO,
    HintUpdateRepositoryDTO,
    HintUpdateServiceDTO,
)
from quiz.dtos.modules import (
    # LessonTestCreateRepositoryDTO,
    # LessonTestCreateServiceDTO,
    # LessonTestRepositoryDTO,
    # LessonTestServiceDTO,
    ModuleLessonCreateRepositoryDTO,
    ModuleLessonCreateServiceDTO,
    ModuleLessonRepositoryDTO,
    ModuleLessonServiceDTO,
    # ModuleTestCreateRepositoryDTO,
    # ModuleTestCreateServiceDTO,
    # ModuleTestRepositoryDTO,
    # ModuleTestServiceDTO,
    SubjectModuleCreateRepositoryDTO,
    SubjectModuleCreateServiceDTO,
    SubjectModuleRepositoryDTO,
    SubjectModuleServiceDTO,
    SubjectModuleUpdateRepositoryDTO,
    SubjectModuleUpdateServiceDTO,
)
from quiz.dtos.questions import (
    # Difficulty,
    # ImportQuestionCreateDTO,
    QuestionCreateRepositoryDTO,
    QuestionCreateServiceDTO,
    # QuestionQueryRepositoryDTO,
    QuestionRepositoryDTO,
    QuestionServiceDTO,
    QuestionUpdateRepositoryDTO,
    QuestionUpdateServiceDTO,
)

# from quiz.dtos.statistic import (
#     EntStatisticDailyDTO,
#     EntStatisticDailyRepositoryDTO,
#     EntStatisticRepositoryDTO,
#     EntStatisticServiceDTO,
#     TopicStatisticDailyDTO,
#     TopicStatisticDailyRepositoryDTO,
#     TopicStatisticRepositoryDTO,
#     TopicStatisticServiceDTO,
# )
from quiz.dtos.subject import (
    SubjectCreateServiceDTO,
    SubjectServiceDTO,
    SubjectUpdateRepositoryDTO,
    SubjectUpdateServiceDTO,
)
from quiz.dtos.text_blocks import TextBlockRepositoryDTO, TextBlockServiceDTO
from quiz.dtos.topic import (
    TopicCreateServiceDTO,
    TopicServiceDTO,
    TopicUpdateRepositoryDTO,
    TopicUpdateServiceDTO,
)
from quiz.dtos.trainer_attempts import (
    TrainerAttemptCreateRepositoryDTO,
    TrainerAttemptCreateServiceDTO,
    # TrainerAttemptRepositoryDTO,
    # TrainerAttemptServiceDTO,
)
from quiz.dtos.trainers import TrainerRepositoryDTO

# , TrainerServiceDTO
from quiz.dtos.variants import (
    VariantCreateRepositoryDTO,
    VariantCreateServiceDTO,
    # VariantRepositoryDTO,
    VariantServiceDTO,
    VariantUpdateRepositoryDTO,
    VariantUpdateServiceDTO,
)

# from quiz.models.daily_tests import (
#     DailyTestAttempt,
#     DailyTestDeviceToken,
#     DailyTestSubjectPreference,
# )
# from quiz.models.edu_content import (
#     Hint,
#     Question,
#     Variant,
# )
# from quiz.models.trainer import TrainerAttempt, TrainerAttemptQuestion


# def to_question_query(
#     student_id: UUID | None = None,
#     topic_id: int | None = None,
#     difficulty: Difficulty | None = None,
#     answered: bool | None = None,
#     type_: QuestionType | None = None,
# ) -> QuestionQueryRepositoryDTO:
#     return QuestionQueryRepositoryDTO(
#         student_id=student_id,
#         topic_id=topic_id,
#         difficulty=difficulty,
#         answered=answered,
#         type=type_,
#     )


def to_test_attempt_create(
    test: TrainerAttemptCreateServiceDTO, trainer: TrainerRepositoryDTO
) -> TrainerAttemptCreateRepositoryDTO:
    return TrainerAttemptCreateRepositoryDTO(
        student_guid=test.student_guid,
        trainer_id=trainer.id,
        score=0,
        status=getattr(test, "status", Status.in_progress),
        started_at=getattr(test, "started_at", datetime.now(UTC).replace(tzinfo=None)),
    )


# def to_test_attempt_service(
#     test_attempt: TrainerAttemptRepositoryDTO,
# ) -> TrainerAttemptServiceDTO:
#     return TrainerAttemptServiceDTO.model_validate(test_attempt)


# def update_question_from_dto(
#     question: QuestionRepositoryDTO, dto: QuestionCreateRepositoryDTO
# ) -> QuestionRepositoryDTO:
#     question.topic_id = dto.topic_id
#     question.type = dto.type
#     question.difficulty = dto.difficulty
#     question.blocks = dto.blocks
#     return question


# def update_hint_from_dto(
#     hint: HintRepositoryDTO, dto: HintCreateRepositoryDTO
# ) -> HintRepositoryDTO:
#     hint.blocks = dto.blocks
#     return hint


# def dto_to_question_model(dto: QuestionRepositoryDTO) -> Question:
#     question = Question(
#         id=dto.id, topic_id=dto.topic_id, difficulty=dto.difficulty, type=dto.type
#     )

#     if dto.hint:
#         question.hint = Hint(blocks=dto.hint.blocks)

#     question.variants = [
#         Variant(blocks=variant.blocks, is_correct=variant.is_correct)
#         for variant in dto.variants
#     ]

#     return question


# def to_variant_dto(variant: Variant) -> VariantRepositoryDTO:
#     return VariantRepositoryDTO.custom(variant)


# def to_question_dto(taq: TrainerAttemptQuestion) -> QuestionRepositoryDTO:
#     return QuestionRepositoryDTO.custom(taq.question)


# def to_test_details_dto_from_test_attempt(
#     attempt: TrainerAttempt,
# ) -> TrainerAttemptServiceDTO:
#     return TrainerAttemptServiceDTO(
#         id=attempt.id,
#         trainer_id=attempt.trainer_id,
#         student_guid=attempt.student_guid,
#         status=attempt.status,
#         questions=[to_question_dto(taq, attempt.type) for taq in attempt.questions],
#         started_at=attempt.started_at,
#         completed_at=attempt.completed_at,
#     )


def to_variant_create_repo(
    variant: VariantCreateServiceDTO,
) -> VariantCreateRepositoryDTO:
    return VariantCreateRepositoryDTO(
        blocks=[
            TextBlockRepositoryDTO(
                order=block.order, type=block.type, value=block.value
            )
            for block in variant.blocks
        ],
        is_correct=variant.is_correct,
        weight=variant.weight,
    )


def to_hint_create_repo(hint: HintCreateServiceDTO) -> HintCreateRepositoryDTO:
    return HintCreateRepositoryDTO(
        blocks=[
            TextBlockRepositoryDTO(
                order=block.order, type=block.type, value=block.value
            )
            for block in hint.blocks
        ]
    )


def to_question_create_repo(
    question: QuestionCreateServiceDTO,
) -> QuestionCreateRepositoryDTO:
    data = {
        "topic_id": question.topic_id,
        "subject_id": question.subject_id,
        "difficulty": question.difficulty,
        "type": question.type,
        "blocks": [TextBlockRepositoryDTO.model_validate(b) for b in question.blocks],
        "variants": [to_variant_create_repo(v) for v in question.variants],
        "hint": to_hint_create_repo(question.hint) if question.hint else None,
        "task_description_ru": getattr(question, "task_description_ru", None),
        "task_description_kk": getattr(question, "task_description_kk", None),
        "question_translation_ru": getattr(question, "question_translation_ru", None),
        "question_translation_kk": getattr(question, "question_translation_kk", None),
        "explanation_ru": getattr(question, "explanation_ru", None),
        "explanation_kk": getattr(question, "explanation_kk", None),
    }

    if hasattr(question, "ent_option_id") and question.ent_option_id is not None:
        data["ent_option_id"] = question.ent_option_id

    return QuestionCreateRepositoryDTO(**data)


def to_question_service(question_repo: QuestionRepositoryDTO) -> QuestionServiceDTO:
    """Convert QuestionRepositoryDTO to QuestionServiceDTO"""
    question_blocks = [
        TextBlockServiceDTO.model_validate(b) for b in question_repo.blocks
    ]

    hint_service = None
    if question_repo.hint:
        hint_blocks = [
            TextBlockServiceDTO.model_validate(b) for b in question_repo.hint.blocks
        ]
        hint_service = HintServiceDTO(
            id=question_repo.hint.id, guid=question_repo.hint.guid, blocks=hint_blocks
        )

    variants_service = []
    for variant in question_repo.variants:
        variant_blocks = [TextBlockServiceDTO.model_validate(b) for b in variant.blocks]
        variants_service.append(
            VariantServiceDTO(
                id=variant.id,
                guid=variant.guid,
                question_id=variant.question_id,
                blocks=variant_blocks,
                is_correct=variant.is_correct,
                weight=variant.weight,
            )
        )

    return QuestionServiceDTO(
        id=question_repo.id,
        guid=question_repo.guid,
        topic_id=question_repo.topic_id,
        subject_id=question_repo.subject_id,
        difficulty=question_repo.difficulty,
        type=question_repo.type,
        blocks=question_blocks,
        hint=hint_service,
        variants=variants_service,
        task_description_ru=getattr(question_repo, "task_description_ru", None),
        task_description_kk=getattr(question_repo, "task_description_kk", None),
        question_translation_ru=getattr(question_repo, "question_translation_ru", None),
        question_translation_kk=getattr(question_repo, "question_translation_kk", None),
        explanation_ru=getattr(question_repo, "explanation_ru", None),
        explanation_kk=getattr(question_repo, "explanation_kk", None),
    )


# def to_hint_service(hint: HintRepositoryDTO) -> HintServiceDTO:
#     return HintServiceDTO(
#         id=hint.id, blocks=[TextBlockServiceDTO.model_validate(b) for b in hint.blocks]
#     )


# def to_variant_service(variant: VariantRepositoryDTO) -> VariantServiceDTO:
#     return VariantServiceDTO(
#         id=variant.id,
#         blocks=[TextBlockServiceDTO.model_validate(b) for b in variant.blocks],
#         is_correct=variant.is_correct,
#         weight=variant.weight,
#     )


def to_topic_service(topic: TopicRepositoryDTO) -> TopicServiceDTO:
    return TopicServiceDTO(id=topic.id, subject_id=topic.subject_id, name=topic.name)


def to_subject_service(subject: SubjectRepositoryDTO, file_service=None) -> SubjectServiceDTO:
    image = subject.image or ""
    if file_service is not None and image:
        image = file_service.get_subject_image_url(image) or ""
    return SubjectServiceDTO(
        id=subject.id,
        name=subject.name,
        type=subject.type,
        image=image,
    )


def to_hint_update_repo(hint: HintUpdateServiceDTO) -> HintUpdateRepositoryDTO:
    return HintUpdateRepositoryDTO(
        blocks=(
            [TextBlockRepositoryDTO.model_validate(b) for b in hint.blocks]
            if hint.blocks
            else None
        )
    )


def to_variant_update_repo(
    variant: VariantUpdateServiceDTO,
) -> VariantUpdateRepositoryDTO:
    return VariantUpdateRepositoryDTO(
        blocks=(
            [TextBlockRepositoryDTO.model_validate(b) for b in variant.blocks]
            if variant.blocks
            else None
        ),
        is_correct=variant.is_correct,
        weight=variant.weight,
    )


def to_question_update_repo(
    question: QuestionUpdateServiceDTO,
) -> QuestionUpdateRepositoryDTO:
    return QuestionUpdateRepositoryDTO(
        subject_id=question.subject_id,
        topic_id=question.topic_id,
        difficulty=question.difficulty,
        type=question.type,
        blocks=(
            [TextBlockRepositoryDTO.model_validate(b) for b in question.blocks]
            if question.blocks
            else None
        ),
        hint=to_hint_update_repo(question.hint) if question.hint else None,
        variants=(
            [to_variant_update_repo(variant) for variant in question.variants]
            if question.variants
            else None
        ),
        task_description_ru=getattr(question, "task_description_ru", None),
        task_description_kk=getattr(question, "task_description_kk", None),
        question_translation_ru=getattr(question, "question_translation_ru", None),
        question_translation_kk=getattr(question, "question_translation_kk", None),
        explanation_ru=getattr(question, "explanation_ru", None),
        explanation_kk=getattr(question, "explanation_kk", None),
    )


def to_subject_update_repository(
    subject_update_service: SubjectUpdateServiceDTO,
) -> SubjectUpdateRepositoryDTO:
    return SubjectUpdateRepositoryDTO(
        **subject_update_service.model_dump(exclude_unset=True)
    )


def to_subject_create_repository(
    subject_create_service: SubjectCreateServiceDTO,
) -> SubjectCreateRepositoryDTO:
    return SubjectCreateRepositoryDTO(**subject_create_service.model_dump())


def to_topic_update_repository(
    topic_update_service: TopicUpdateServiceDTO,
) -> TopicUpdateRepositoryDTO:
    return TopicUpdateRepositoryDTO(**topic_update_service.model_dump())


def to_topic_create_repository(
    topic_create_service: TopicCreateServiceDTO,
) -> TopicCreateRepositoryDTO:
    return TopicCreateRepositoryDTO(**topic_create_service.model_dump())


def to_service_question(question: QuestionRepositoryDTO) -> QuestionServiceDTO:
    return QuestionServiceDTO.model_validate(question)


def to_ent_attempt_service(
    ent_attempt: EntAttemptRepositoryDTO, questions: list
) -> EntAttemptServiceDTO:
    from quiz.dtos.ent_attempts import SubjectQuestionsDTO

    if questions and isinstance(questions[0], SubjectQuestionsDTO):
        question_count = sum(
            len(subject_group.questions) for subject_group in questions
        )
    else:
        question_count = len(questions)

    return EntAttemptServiceDTO(
        guid=ent_attempt.guid,
        id=ent_attempt.id,
        ent_option_id=ent_attempt.ent_option_id,
        question_count=question_count,
        student_guid=ent_attempt.student_guid,
        status=ent_attempt.status,
        score=ent_attempt.score,
        started_at=ent_attempt.started_at,
        deadline_at=ent_attempt.deadline_at,
        completed_at=ent_attempt.completed_at,
        exam_type=ent_attempt.exam_type,
        subject_combination_id=ent_attempt.subject_combination_id,
        current_question_index=ent_attempt.current_question_index,
        full_exam_question_ids=ent_attempt.full_exam_question_ids,
        questions=questions,
    )


def to_ent_attempt_create_repository(
    ent_attempt: EntAttemptCreateServiceDTO,
) -> EntAttemptCreateRepositoryDTO:
    return EntAttemptCreateRepositoryDTO(**ent_attempt.model_dump())


def to_ent_option_get_repo(option_params_dto: EntOptionsGetServiceDTO):
    return EntOptionsGetRepositoryDTO.model_validate(option_params_dto.model_dump())


# def to_ent_attempt_option_statistic_service(
#     stat: EntAttemptOptionStatisticRepositoryDTO,
# ) -> EntAttemptOptionStatisticServiceDTO:
#     return EntAttemptOptionStatisticServiceDTO(
#         score=stat.score,
#         skiped=stat.skiped,
#         correct=stat.correct,
#         partial_correct=stat.partial_correct,
#         incorrect=stat.incorrect,
#         spend_time=stat.spend_time,
#     )


# def to_ent_option_create_service(
#     ent_create: EntOptionCreateDTO,
# ) -> EntOptionCreateServiceDTO:
#     return EntOptionCreateServiceDTO(**ent_create.model_dump())


# def to_ent_option_update_service(
#     ent_update: EntOptionCreateDTO,
# ) -> EntOptionUpdateServiceDTO:
#     return EntOptionUpdateServiceDTO(**ent_update.model_dump())


# def convert_import_to_service_dto(
#     import_dto: ImportQuestionCreateDTO, subject_id: int, topic_id: int | None = None
# ) -> QuestionCreateServiceDTO:
#     """Конвертирует DTO импорта в DTO сервиса для создания вопроса"""
#     variant_dtos = []
#     for import_variant in import_dto.answers:
#         variant_dtos.append(
#             VariantCreateServiceDTO(
#                 blocks=import_variant.blocks,
#                 is_correct=import_variant.is_correct,
#                 weight=import_variant.weight,
#             )
#         )

#     hint_dto = None
#     if import_dto.hint_blocks:
#         hint_dto = HintCreateServiceDTO(blocks=import_dto.hint_blocks)

#     return QuestionCreateServiceDTO(
#         topic_id=topic_id,
#         subject_id=subject_id,
#         ent_option_id=None,
#         difficulty=import_dto.difficulty,
#         type=import_dto.type,
#         blocks=import_dto.question_blocks,
#         variants=variant_dtos,
#         hint=hint_dto,
#     )


# def to_trainer_service(trainer: TrainerRepositoryDTO) -> TrainerServiceDTO:
#     """Convert TrainerRepositoryDTO to TrainerServiceDTO"""
#     return TrainerServiceDTO(
#         id=trainer.id, topic_id=trainer.topic_id, name=trainer.name, guid=trainer.guid
#     )


# def to_topic_statistic_service_dto(
#     overall_repo: TopicStatisticRepositoryDTO,
#     daily_repo: list[TopicStatisticDailyRepositoryDTO],
# ) -> TopicStatisticServiceDTO:
#     """Конвертирует репозиторные DTO статистики тренажеров в сервисные"""
#     overall_daily = TopicStatisticDailyDTO(
#         date=date.today(),
#         total=overall_repo.total,
#         correct=overall_repo.correct,
#         partial_correct=overall_repo.partial_correct,
#         incorrect=overall_repo.incorrect,
#         skiped=overall_repo.skiped,
#         avg_spend_time=overall_repo.avg_spend_time,
#     )

#     daily_dtos = [
#         TopicStatisticDailyDTO(
#             date=daily.date,
#             total=daily.total,
#             correct=daily.correct,
#             partial_correct=daily.partial_correct,
#             incorrect=daily.incorrect,
#             skiped=daily.skiped,
#             avg_spend_time=daily.avg_spend_time,
#         )
#         for daily in daily_repo
#     ]

#     return TopicStatisticServiceDTO(overall=overall_daily, daily=daily_dtos)


# def to_ent_statistic_service_dto(
#     overall_repo: EntStatisticRepositoryDTO,
#     daily_repo: list[EntStatisticDailyRepositoryDTO],
# ) -> EntStatisticServiceDTO:
#     """Конвертирует репозиторные DTO статистики ЕНТ в сервисные"""
#     overall_daily = EntStatisticDailyDTO(
#         date=date.today(),
#         avg_score=overall_repo.avg_score,
#         tries=overall_repo.tries,
#         avg_spend_time=overall_repo.avg_spend_time,
#     )

#     daily_dtos = [
#         EntStatisticDailyDTO(
#             date=daily.date,
#             avg_score=daily.avg_score,
#             tries=daily.tries,
#             avg_spend_time=daily.avg_spend_time,
#         )
#         for daily in daily_repo
#     ]

#     return EntStatisticServiceDTO(overall=overall_daily, daily=daily_dtos)


# def to_question_repository_dto(
#     question_service: QuestionServiceDTO,
# ) -> QuestionRepositoryDTO:
#     """Convert QuestionServiceDTO to QuestionRepositoryDTO"""
#     return QuestionRepositoryDTO(
#         id=question_service.id,
#         guid=question_service.guid,
#         topic_id=question_service.topic_id,
#         subject_id=question_service.subject_id,
#         difficulty=question_service.difficulty,
#         type=question_service.type,
#         blocks=[
#             TextBlockRepositoryDTO(
#                 order=block.order, type=block.type, value=block.value
#             )
#             for block in question_service.blocks
#         ],
#         hint=(
#             to_hint_repository_dto(question_service.hint)
#             if question_service.hint
#             else None
#         ),
#         variants=[
#             to_variant_repository_dto(variant) for variant in question_service.variants
#         ],
#     )


# def to_hint_repository_dto(hint_service: HintServiceDTO) -> HintRepositoryDTO:
#     """Convert HintServiceDTO to HintRepositoryDTO"""
#     return HintRepositoryDTO(
#         id=hint_service.id,
#         guid=hint_service.guid,
#         blocks=[
#             TextBlockRepositoryDTO(
#                 order=block.order, type=block.type, value=block.value
#             )
#             for block in hint_service.blocks
#         ],
#     )


# def to_variant_repository_dto(
#     variant_service: VariantServiceDTO,
# ) -> VariantRepositoryDTO:
#     """Convert VariantServiceDTO to VariantRepositoryDTO"""
#     return VariantRepositoryDTO(
#         id=variant_service.id,
#         guid=variant_service.guid,
#         question_id=variant_service.question_id,
#         blocks=[
#             TextBlockRepositoryDTO(
#                 order=block.order, type=block.type, value=block.value
#             )
#             for block in variant_service.blocks
#         ],
#         is_correct=variant_service.is_correct,
#         weight=variant_service.weight,
#     )


# def to_subject_preference_dto(
#     preference: DailyTestSubjectPreference,
# ) -> SubjectPreferenceDTO:
#     """Конвертировать DailyTestSubjectPreference в DTO"""
#     return SubjectPreferenceDTO(
#         subject_id=preference.subject.id,
#         subject_name=preference.subject.name,
#         image=(
#             f"{LEGACY_CDN_BASE}{preference.subject.image}"
#             if preference.subject.image
#             else None
#         ),
#         is_default=preference.is_default,
#     )


# def to_daily_test_history_item_dto(
#     attempt: DailyTestAttempt,
# ) -> DailyTestHistoryItemDTO:
#     """Конвертировать DailyTestAttempt в DTO истории"""
#     return DailyTestHistoryItemDTO(
#         id=attempt.id,
#         guid=attempt.guid,
#         test_date=attempt.test_date,
#         subject_id=attempt.subject_id,
#         subject_name=attempt.subject.name if attempt.subject else None,
#         status=attempt.status,
#         score=attempt.score,
#         correct_answers=attempt.correct_answers,
#         incorrect_answers=attempt.incorrect_answers,
#         skipped_answers=attempt.skipped_answers,
#         total_questions=len(attempt.questions) if hasattr(attempt, "questions") else 0,
#         completed_at=attempt.completed_at,
#     )


# def to_daily_test_result_dto(
#     attempt: DailyTestAttempt,
#     correct_count: int,
#     incorrect_count: int,
#     skipped_count: int,
#     percentage: float,
# ) -> DailyTestResultDTO:
#     """Конвертировать DailyTestAttempt в DTO результата"""
#     total_questions = correct_count + incorrect_count + skipped_count

#     return DailyTestResultDTO(
#         attempt_id=attempt.id,
#         test_date=attempt.test_date,
#         score=attempt.score,
#         correct_answers=correct_count,
#         incorrect_answers=incorrect_count,
#         skipped_answers=skipped_count,
#         total_questions=total_questions,
#         percentage=round(percentage, 2),
#         completed_at=datetime.now(UTC),
#         subject_id=attempt.subject_id,
#         subject_name=attempt.subject.name if attempt.subject else None,
#     )


# def to_daily_test_device_token_dto(
#     token: DailyTestDeviceToken,
# ) -> DailyTestDeviceTokenDTO:
#     """Конвертировать DailyTestDeviceToken в DTO"""
#     return DailyTestDeviceTokenDTO(
#         id=token.id,
#         student_guid=token.student_guid,
#         token=token.token,
#         platform=token.platform,
#         device_id=token.device_id,
#         created_at=token.created_at,
#         updated_at=token.updated_at,
#     )


def to_subject_module_repository(
    service_dto: SubjectModuleCreateServiceDTO,
) -> SubjectModuleCreateRepositoryDTO:
    """Convert SubjectModuleCreateServiceDTO to SubjectModuleCreateRepositoryDTO"""
    return SubjectModuleCreateRepositoryDTO(
        title=service_dto.title,
        description=service_dto.description,
        order_index=service_dto.order_index,
        is_active=service_dto.is_active,
        subject_id=service_dto.subject_id,
    )


def to_subject_module_service(
    repo_dto: SubjectModuleRepositoryDTO,
) -> SubjectModuleServiceDTO:
    """Convert SubjectModuleRepositoryDTO to SubjectModuleServiceDTO"""
    return SubjectModuleServiceDTO(
        id=repo_dto.id,
        guid=repo_dto.guid,
        subject_id=repo_dto.subject_id,
        title=repo_dto.title,
        description=repo_dto.description,
        order_index=repo_dto.order_index,
        is_active=repo_dto.is_active,
        created_at=repo_dto.created_at,
        updated_at=repo_dto.updated_at,
        lesson_count=repo_dto.lesson_count,
    )


def to_module_lesson_repository(
    service_dto: ModuleLessonCreateServiceDTO,
) -> ModuleLessonCreateRepositoryDTO:
    """Convert ModuleLessonCreateServiceDTO to ModuleLessonCreateRepositoryDTO"""
    return ModuleLessonCreateRepositoryDTO(
        title=service_dto.title,
        description=service_dto.description,
        video_url=service_dto.video_url,
        presentation_url=service_dto.presentation_url,
        order_index=service_dto.order_index,
        difficulty=service_dto.difficulty,
        is_published=service_dto.is_published,
        published_at=service_dto.published_at,
        module_id=service_dto.module_id,
        topic_id=service_dto.topic_id,
    )


def to_module_lesson_service(
    repo_dto: ModuleLessonRepositoryDTO,
) -> ModuleLessonServiceDTO:
    """Convert ModuleLessonRepositoryDTO to ModuleLessonServiceDTO"""
    return ModuleLessonServiceDTO(
        id=repo_dto.id,
        guid=repo_dto.guid,
        module_id=repo_dto.module_id,
        topic_id=repo_dto.topic_id,
        title=repo_dto.title,
        description=repo_dto.description,
        video_url=repo_dto.video_url,
        presentation_url=repo_dto.presentation_url,
        order_index=repo_dto.order_index,
        difficulty=repo_dto.difficulty,
        is_published=repo_dto.is_published,
        published_at=repo_dto.published_at,
        created_at=repo_dto.created_at,
        updated_at=repo_dto.updated_at,
    )


# def to_lesson_test_repository(
#     service_dto: LessonTestCreateServiceDTO,
# ) -> LessonTestCreateRepositoryDTO:
#     """Convert LessonTestCreateServiceDTO to LessonTestCreateRepositoryDTO"""
#     return LessonTestCreateRepositoryDTO(**service_dto.model_dump())


# def to_lesson_test_service(repo_dto: LessonTestRepositoryDTO) -> LessonTestServiceDTO:
#     """Convert LessonTestRepositoryDTO to LessonTestServiceDTO"""
#     return LessonTestServiceDTO(
#         id=repo_dto.id,
#         guid=repo_dto.guid,
#         lesson_id=repo_dto.lesson_id,
#         title=repo_dto.title,
#         description=repo_dto.description,
#         pass_score_percentage=repo_dto.pass_score_percentage,
#         time_limit_minutes=repo_dto.time_limit_minutes,
#         max_attempts=repo_dto.max_attempts,
#         is_active=repo_dto.is_active,
#         created_at=repo_dto.created_at,
#         updated_at=repo_dto.updated_at,
#     )


# def to_module_test_repository(
#     service_dto: ModuleTestCreateServiceDTO,
# ) -> ModuleTestCreateRepositoryDTO:
#     """Convert ModuleTestCreateServiceDTO to ModuleTestCreateRepositoryDTO"""
#     return ModuleTestCreateRepositoryDTO(**service_dto.model_dump())


# def to_module_test_service(repo_dto: ModuleTestRepositoryDTO) -> ModuleTestServiceDTO:
#     """Convert ModuleTestRepositoryDTO to ModuleTestServiceDTO"""
#     return ModuleTestServiceDTO(
#         id=repo_dto.id,
#         guid=repo_dto.guid,
#         module_id=repo_dto.module_id,
#         title=repo_dto.title,
#         description=repo_dto.description,
#         pass_score_percentage=repo_dto.pass_score_percentage,
#         time_limit_minutes=repo_dto.time_limit_minutes,
#         max_attempts=repo_dto.max_attempts,
#         is_active=repo_dto.is_active,
#         created_at=repo_dto.created_at,
#         updated_at=repo_dto.updated_at,
#     )


def to_subject_module_update_repository(
    service_dto: SubjectModuleUpdateServiceDTO,
) -> SubjectModuleUpdateRepositoryDTO:
    return SubjectModuleUpdateRepositoryDTO(
        title=service_dto.title,
        description=service_dto.description,
        order_index=service_dto.order_index,
        is_active=service_dto.is_active,
        subject_id=service_dto.subject_id,
    )
