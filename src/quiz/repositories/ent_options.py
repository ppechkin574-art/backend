from typing import Protocol
from uuid import UUID

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.orm import Session, joinedload

from quiz.dtos.ent_attempts import EntAttemptOptionStatisticRepositoryDTO
from quiz.dtos.ent_options import (
    EntOptionCreateDTO,
    EntOptionsGetRepositoryDTO,
    EntOptionsRepositoryDTO,
    EntOptionUpdateDTO,
)
from quiz.dtos.enums import Status
from quiz.dtos.questions import QuestionRepositoryDTO
from quiz.exceptions import EntOptionAlreadyExist, QuestionNotFound
from quiz.models.edu_content import Question, Subject, Variant
from quiz.models.ent import EntAttempt, EntAttemptAnswer, EntOption, EntOptionQuestion
from quiz.models.text_blocks import TextBlockLink


class EntOptionsRepositoryInterface(Protocol):
    def get_ent_options(self, ent_option_params: EntOptionsGetRepositoryDTO) -> list[EntOptionsRepositoryDTO]:
        raise NotImplementedError

    def get_option_questions(self, ent_option_id: int) -> list[QuestionRepositoryDTO]:
        raise NotImplementedError

    def get_option_by_number(self, option_number: int) -> EntOptionsRepositoryDTO | None:
        # deprecated
        raise NotImplementedError

    def get_by_id(self, ent_option_id: int) -> EntOptionsRepositoryDTO | None:
        raise NotImplementedError

    def create(self, ent_create: EntOptionCreateDTO) -> EntOptionsRepositoryDTO:
        raise NotImplementedError

    def update(self, ent_option_id: int, ent_update: EntOptionUpdateDTO) -> EntOptionsRepositoryDTO:
        raise NotImplementedError

    def delete(self, ent_option_id: int) -> None:
        raise NotImplementedError

    def add_question_to_ent(self, ent_option_id: int, question_id: int) -> None:
        raise NotImplementedError

    def remove_question_from_ent(self, ent_option_id: int, question_id: int) -> None:
        raise NotImplementedError

    def get_all_ent_options(
        self, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[EntOptionsRepositoryDTO], int]:
        raise NotImplementedError

    def get_questions_by_ent_option(self, ent_option_id: int) -> list[QuestionRepositoryDTO]:
        raise NotImplementedError

    def get_count_by_subject(self, subject_id: int) -> int:
        raise NotImplementedError

    def list_query(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[EntOptionsRepositoryDTO], int, int]:
        raise NotImplementedError

    def check_question_in_option(self, ent_option_id: int, question_id: int) -> bool:
        raise NotImplementedError

    def get_questions_ids(self, ent_option_id: int) -> list[int]:
        raise NotImplementedError

    def bulk_add_questions(self, ent_option_id: int, question_ids: list[int]) -> None:
        raise NotImplementedError

    def bulk_remove_questions(self, ent_option_id: int, question_ids: list[int]) -> None:
        raise NotImplementedError


class EntOptionRepository:
    def __init__(self, session: Session):
        self._session = session

    def _to_repository_dto(self, option, subject_name: str = None) -> EntOptionsRepositoryDTO:
        """Универсальный метод преобразования в DTO"""
        if subject_name is None and hasattr(option, "subject") and option.subject:
            subject_name = option.subject.name

        return EntOptionsRepositoryDTO(
            id=option.id,
            subject=subject_name or "Unknown",
            subject_id=option.subject_id,
            option_number=option.option_number,
            best_attempt=None,
        )

    def get_ent_options(self, ent_option_params: EntOptionsGetRepositoryDTO) -> list[EntOptionsRepositoryDTO]:
        query = select(Subject.name, EntOption).join(Subject, Subject.id == EntOption.subject_id)

        if ent_option_params.subject_id:
            query = query.where(EntOption.subject_id == ent_option_params.subject_id)

        options = self._session.execute(query).all()
        result = []

        for subject_name, ent_option in options:
            ent_option_dto = self._to_repository_dto(ent_option, subject_name)

            if hasattr(ent_option_params, "student_guid") and ent_option_params.student_guid:
                best_attempt = self._get_best_attempt_for_option(ent_option.id, ent_option_params.student_guid)
                ent_option_dto.best_attempt = best_attempt

            result.append(ent_option_dto)

        return result

    def _get_best_attempt_for_option(
        self, ent_option_id: int, student_guid: UUID
    ) -> EntAttemptOptionStatisticRepositoryDTO | None:
        """Получить статистику лучшей попытки для варианта"""
        best_attempt_query = (
            select(
                EntAttempt.id,
                EntAttempt.score,
                func.extract("epoch", EntAttempt.completed_at - EntAttempt.started_at).label("spend_time_seconds"),
            )
            .where(
                EntAttempt.ent_option_id == ent_option_id,
                EntAttempt.student_guid == student_guid,
                EntAttempt.status == Status.completed,
            )
            .order_by(EntAttempt.score.desc())
        )

        result = self._session.execute(best_attempt_query).first()
        if not result:
            return None

        best_attempt_id, score, spend_time_seconds = result
        spend_time = int(spend_time_seconds) if spend_time_seconds is not None else 0

        answer_scores = (
            select(
                EntAttemptAnswer.ent_attempt_id,
                Variant.question_id,
                case(
                    (EntAttemptAnswer.variant_id.is_(None), literal_column("'skiped'")),
                    else_=case(
                        (
                            func.round(func.sum(Variant.weight)) == 1 and func.count(Variant.id) == 1,
                            literal_column("'correct'"),
                        ),
                        (
                            func.round(func.sum(Variant.weight)) == 2 and func.count(Variant.id) > 1,
                            literal_column("'correct'"),
                        ),
                        (
                            func.round(func.sum(Variant.weight)) == 1 and func.count(Variant.id) > 1,
                            literal_column("'partial_correct'"),
                        ),
                        else_=literal_column("'incorrect'"),
                    ),
                ).label("result"),
            )
            .select_from(EntAttemptAnswer)
            .outerjoin(Variant, Variant.id == EntAttemptAnswer.variant_id)
            .where(EntAttemptAnswer.ent_attempt_id == best_attempt_id)
            .group_by(
                EntAttemptAnswer.ent_attempt_id,
                Variant.question_id,
                EntAttemptAnswer.variant_id,
            )
            .cte("answer_scores")
        )

        stats_query = select(
            func.count().filter(answer_scores.c.result == "correct").label("correct_count"),
            func.count().filter(answer_scores.c.result == "partial_correct").label("partial_correct_count"),
            func.count().filter(answer_scores.c.result == "skiped").label("skipped_count"),
            func.count().filter(answer_scores.c.result == "incorrect").label("incorrect_count"),
        )

        row = self._session.execute(stats_query).one_or_none()
        if row:
            correct, partial_correct, skiped, incorrect = row
        else:
            correct, partial_correct, skiped, incorrect = 0, 0, 0, 0

        return EntAttemptOptionStatisticRepositoryDTO(
            attempt_id=best_attempt_id,
            score=score or 0,
            correct=correct,
            partial_correct=partial_correct,
            incorrect=incorrect,
            skiped=skiped,
            spend_time=spend_time,
        )

    def get_option_questions(self, ent_option_id: int) -> list[QuestionRepositoryDTO]:
        """Получить вопросы варианта (алиас для get_questions_by_ent_option)"""
        return self.get_questions_by_ent_option(ent_option_id)

    def get_questions_by_ent_option(self, ent_option_id: int) -> list[QuestionRepositoryDTO]:
        """Получить вопросы ЕНТ варианта"""
        questions = (
            self._session.query(Question)
            .options(
                joinedload(Question.link).joinedload(TextBlockLink.blocks),
                joinedload(Question.variants).joinedload(Variant.link).joinedload(TextBlockLink.blocks),
                joinedload(Question.ent_options),
            )
            .join(EntOptionQuestion, Question.id == EntOptionQuestion.question_id)
            .filter(EntOptionQuestion.ent_option_id == ent_option_id)
            .all()
        )

        if not questions:
            raise QuestionNotFound(f"No questions found for ENT option {ent_option_id}")

        return [QuestionRepositoryDTO.custom(q) for q in questions]

    def get_option_by_number(self, option_number: int) -> EntOptionsRepositoryDTO | None:
        # deprecated
        """Получить вариант ЕНТ по номеру"""
        option = (
            self._session.query(EntOption)
            .options(joinedload(EntOption.subject))
            .filter(EntOption.option_number == option_number)
            .first()
        )

        if option:
            return self._to_repository_dto(option)
        return None

    def get_by_id(self, ent_option_id: int) -> EntOptionsRepositoryDTO | None:
        """Получить ЕНТ вариант по ID"""
        option = (
            self._session.query(EntOption)
            .options(joinedload(EntOption.subject))
            .filter(EntOption.id == ent_option_id)
            .first()
        )

        if option:
            return self._to_repository_dto(option)
        return None

    def create(self, ent_create: EntOptionCreateDTO) -> EntOptionsRepositoryDTO:
        """Создать ЕНТ вариант с проверкой уникальности в рамках предмета"""
        existing = (
            self._session.query(EntOption)
            .filter_by(subject_id=ent_create.subject_id, option_number=ent_create.option_number)
            .first()
        )
        if existing:
            raise EntOptionAlreadyExist(
                f"ENT option with number {ent_create.option_number} already exists for subject {ent_create.subject_id}"
            )

        option = EntOption(option_number=ent_create.option_number, subject_id=ent_create.subject_id)
        self._session.add(option)
        self._session.flush()

        return self._to_repository_dto(option)

    def update(self, ent_option_id: int, ent_update: EntOptionUpdateDTO) -> EntOptionsRepositoryDTO:
        """Обновить ЕНТ вариант"""
        option = self._session.get(EntOption, ent_option_id)
        if not option:
            return None

        if ent_update.option_number is not None and ent_update.option_number != option.option_number:
            subject_id = ent_update.subject_id if ent_update.subject_id is not None else option.subject_id
            existing = (
                self._session.query(EntOption)
                .filter(
                    EntOption.subject_id == subject_id,
                    EntOption.option_number == ent_update.option_number,
                    EntOption.id != ent_option_id,
                )
                .first()
            )
            if existing:
                raise EntOptionAlreadyExist(
                    f"ENT option with number {ent_update.option_number} already exists for subject {subject_id}"
                )
            option.option_number = ent_update.option_number

        if ent_update.subject_id is not None and ent_update.subject_id != option.subject_id:
            option.subject_id = ent_update.subject_id

        self._session.flush()
        return self._to_repository_dto(option)

    def delete(self, ent_option_id: int) -> None:
        """Удалить ЕНТ вариант"""
        option = self._session.get(EntOption, ent_option_id)
        if option:
            self._session.delete(option)

    def add_question_to_ent(self, ent_option_id: int, question_id: int) -> None:
        """Добавить вопрос в ЕНТ вариант"""
        existing = (
            self._session.query(EntOptionQuestion)
            .filter_by(ent_option_id=ent_option_id, question_id=question_id)
            .first()
        )

        if not existing:
            ent_option_question = EntOptionQuestion(ent_option_id=ent_option_id, question_id=question_id)
            self._session.add(ent_option_question)

    def remove_question_from_ent(self, ent_option_id: int, question_id: int) -> None:
        """Удалить вопрос из ЕНТ варианта"""
        self._session.query(EntOptionQuestion).filter_by(ent_option_id=ent_option_id, question_id=question_id).delete()

    def get_all_ent_options(
        self, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[EntOptionsRepositoryDTO], int]:
        """Получить все ЕНТ варианты для админки с предметами"""
        query = (
            self._session.query(EntOption)
            .join(Subject, EntOption.subject_id == Subject.id)
            .options(joinedload(EntOption.subject))
        )

        if search:
            query = query.filter(
                Subject.name.ilike(f"%{search}%") | (EntOption.option_number.cast(str).ilike(f"%{search}%"))
            )

        total_count = query.count()

        offset = (page - 1) * page_size
        options = query.offset(offset).limit(page_size).all()

        result = []
        for option in options:
            ent_option_dto = self._to_repository_dto(option)
            result.append(ent_option_dto)

        return result, total_count

    def get_count_by_subject(self, subject_id: int) -> int:
        """Получить количество ЕНТ вариантов по предмету"""
        count = self._session.execute(
            select(func.count(EntOption.id)).where(EntOption.subject_id == subject_id)
        ).scalar()

        return count or 0

    def list_query(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[EntOptionsRepositoryDTO], int, int]:
        """Получить список ЕНТ вариантов с сортировкой и пагинацией"""
        query = select(Subject.name, EntOption).join(Subject, Subject.id == EntOption.subject_id)

        if search:
            query = query.where(
                Subject.name.ilike(f"%{search}%") | (EntOption.option_number.cast(str).ilike(f"%{search}%"))
            )

        if sort_columns and is_sort_ascendings:
            # Здесь должна быть более сложная логика сортировки
            # В реализации нужно маппить названия колонок на атрибуты моделей
            pass

        total_count = self._session.execute(select(func.count()).select_from(query.subquery())).scalar()

        query = query.offset((page - 1) * page_size).limit(page_size)

        options = self._session.execute(query).all()
        result = []

        for subject_name, ent_option in options:
            ent_option_dto = self._to_repository_dto(ent_option, subject_name)
            result.append(ent_option_dto)

        return result, total_count, page

    def get_by_subject_id(self, subject_id: int) -> list[EntOption]:
        """Получить все ENT варианты по subject_id - возвращает модели"""
        return self._session.query(EntOption).filter(EntOption.subject_id == subject_id).all()

    def get_all_ent_options_with_question_counts(self) -> list[tuple[EntOption, int]]:
        """Все ЕНТ варианты с количеством вопросов"""
        stmt = (
            select(
                EntOption,
                func.count(EntOptionQuestion.question_id).label("question_count"),
            )
            .select_from(EntOption)
            .outerjoin(EntOptionQuestion, EntOption.id == EntOptionQuestion.ent_option_id)
            .group_by(EntOption.id)
        )

        result = self._session.execute(stmt).all()
        return [(option, count or 0) for option, count in result]

    def count_questions_by_option(self, ent_option_id: int) -> int:
        """Подсчитать количество вопросов в варианте ЕНТ"""
        return self._session.query(EntOptionQuestion).filter_by(ent_option_id=ent_option_id).count()

    def get_max_option_number(self) -> int | None:
        """Возвращает максимальный номер варианта ЕНТ"""
        result = self._session.query(func.max(EntOption.option_number)).scalar()
        return result

    def get_question_by_id(self, question_id: int):
        """Получить вопрос ЕНТ с вариантами по ID"""
        ent_question = (
            self._session.query(EntOptionQuestion)
            .options(
                joinedload(EntOptionQuestion.question)
                .joinedload(Question.variants)
                .joinedload(Variant.link)
                .joinedload(TextBlockLink.blocks)
            )
            .filter(EntOptionQuestion.question_id == question_id)
            .first()
        )

        if ent_question and ent_question.question:
            return QuestionRepositoryDTO.custom(ent_question.question)
        return None

    def check_question_in_option(self, ent_option_id: int, question_id: int) -> bool:
        """Проверить, содержится ли вопрос в варианте ЕНТ"""
        exists = (
            self._session.query(EntOptionQuestion)
            .filter_by(ent_option_id=ent_option_id, question_id=question_id)
            .first()
        )
        return exists is not None

    def get_questions_ids(self, ent_option_id: int) -> list[int]:
        """Получить список ID вопросов варианта ЕНТ"""
        question_ids = self._session.query(EntOptionQuestion.question_id).filter_by(ent_option_id=ent_option_id).all()
        return [qid for (qid,) in question_ids]

    def bulk_add_questions(self, ent_option_id: int, question_ids: list[int]) -> None:
        """Массово добавить вопросы в вариант ЕНТ"""
        existing_relations = (
            self._session.query(EntOptionQuestion)
            .filter(
                EntOptionQuestion.ent_option_id == ent_option_id,
                EntOptionQuestion.question_id.in_(question_ids),
            )
            .all()
        )

        existing_ids = {rel.question_id for rel in existing_relations}
        new_relations = []

        for question_id in question_ids:
            if question_id not in existing_ids:
                new_relations.append(EntOptionQuestion(ent_option_id=ent_option_id, question_id=question_id))

        if new_relations:
            self._session.bulk_save_objects(new_relations)

    def bulk_remove_questions(self, ent_option_id: int, question_ids: list[int]) -> None:
        """Массово удалить вопросы из варианта ЕНТ"""
        self._session.query(EntOptionQuestion).filter(
            EntOptionQuestion.ent_option_id == ent_option_id,
            EntOptionQuestion.question_id.in_(question_ids),
        ).delete(synchronize_session=False)

    def get_ent_questions_count(self, ent_option_id: int) -> int:
        """Получить количество вопросов в варианте ЕНТ"""
        from quiz.models.ent import EntOption

        option = self._session.query(EntOption).get(ent_option_id)
        if not option:
            return 0

        return len(option.questions) if option.questions else 0

    # def count_questions_by_ent_option(self, ent_option_id: int) -> int:
    #     """Подсчитать количество вопросов в варианте ЕНТ"""
    #     return self._session.query(EntOptionQuestion).filter_by(ent_option_id=ent_option_id).count()

    def get_max_option_number_for_subject(self, subject_id: int) -> int | None:
        """Получить максимальный номер варианта для предмета"""
        result = (
            self._session.query(func.max(EntOption.option_number)).filter(EntOption.subject_id == subject_id).scalar()
        )
        return result

    def get_by_subject_and_number(self, subject_id: int, option_number: int) -> EntOption | None:
        """Найти вариант по предмету и номеру"""
        return (
            self._session.query(EntOption)
            .filter(
                EntOption.subject_id == subject_id,
                EntOption.option_number == option_number,
            )
            .first()
        )
