import logging

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from quiz.dtos.ent_questions import (
    EntOptionQuestionCreateDTO,
    EntOptionQuestionRepositoryDTO,
)
from quiz.models.ent import EntOption, EntOptionQuestion

logger = logging.getLogger()


class EntOptionQuestionRepositoryInterface:
    def create(self, create_dto: EntOptionQuestionCreateDTO) -> EntOptionQuestionRepositoryDTO:
        raise NotImplementedError

    def get_by_ent_option_id(self, ent_option_id: int) -> list[EntOptionQuestionRepositoryDTO]:
        raise NotImplementedError

    def get_by_question_id(self, question_id: int) -> list[EntOptionQuestionRepositoryDTO]:
        raise NotImplementedError

    # def get_questions_by_ent_option_ids(self, ent_option_ids: list[int]) -> list[EntOptionQuestionRepositoryDTO]:
    #     raise NotImplementedError

    def find_ent_option_with_questions(self, question_ids: list[int], subject_id: int) -> int | None:
        """Находит ENT вариант, который содержит ТОЧНО такой же набор вопросов"""
        raise NotImplementedError


class EntOptionQuestionRepository(EntOptionQuestionRepositoryInterface):
    def __init__(self, session: Session):
        self._session = session

    def create(self, create_dto: EntOptionQuestionCreateDTO) -> EntOptionQuestionRepositoryDTO:
        ent_question = EntOptionQuestion(ent_option_id=create_dto.ent_option_id, question_id=create_dto.question_id)
        self._session.add(ent_question)
        self._session.flush()
        return EntOptionQuestionRepositoryDTO.model_validate(ent_question)

    def get_by_ent_option_id(self, ent_option_id: int) -> list[EntOptionQuestionRepositoryDTO]:
        ent_questions = (
            self._session.query(EntOptionQuestion).filter(EntOptionQuestion.ent_option_id == ent_option_id).all()
        )
        return [EntOptionQuestionRepositoryDTO.model_validate(eq) for eq in ent_questions]

    def get_by_question_id(self, question_id: int) -> list[EntOptionQuestionRepositoryDTO]:
        ent_questions = (
            self._session.query(EntOptionQuestion).filter(EntOptionQuestion.question_id == question_id).all()
        )
        return [EntOptionQuestionRepositoryDTO.model_validate(eq) for eq in ent_questions]

    # def get_questions_by_ent_option_ids(self, ent_option_ids: list[int]) -> list[EntOptionQuestionRepositoryDTO]:
    #     ent_questions = (
    #         self._session.query(EntOptionQuestion).filter(EntOptionQuestion.ent_option_id.in_(ent_option_ids)).all()
    #     )
    #     return [EntOptionQuestionRepositoryDTO.model_validate(eq) for eq in ent_questions]

    def find_ent_option_with_questions(self, question_ids: list[int], subject_id: int) -> int | None:
        """
        Находит ENT вариант, который содержит ТОЧНО такой же набор вопросов.
        """
        try:
            if not question_ids:
                return None

            query = text(
                """
                SELECT eo.id, COUNT(eq.question_id) as total_count
                FROM ent_options eo
                JOIN ent_questions eq ON eo.id = eq.ent_option_id
                WHERE eo.subject_id = :subject_id
                GROUP BY eo.id
                HAVING COUNT(eq.question_id) = :question_count
            """
            )

            result = self._session.execute(
                query, {"subject_id": subject_id, "question_count": len(question_ids)}
            ).fetchall()

            if not result:
                return None

            for row in result:
                ent_option_id = row[0]
                option_questions = (
                    self._session.query(EntOptionQuestion)
                    .filter(EntOptionQuestion.ent_option_id == ent_option_id)
                    .all()
                )

                option_question_ids = [eq.question_id for eq in option_questions]

                if set(option_question_ids) == set(question_ids):
                    return ent_option_id

            return None

        except Exception as e:
            logger.exception("Error in find_ent_option_with_questions: %s", str(e))
            return None

    def get_max_option_number(self) -> int | None:
        """Возвращает максимальный номер варианта ЕНТ"""
        result = self._session.query(func.max(EntOption.option_number)).scalar()
        return result
