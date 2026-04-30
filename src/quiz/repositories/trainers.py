from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quiz.dtos.questions import QuestionRepositoryDTO
from quiz.dtos.trainers import TrainerRepositoryDTO
from quiz.models.edu_content import Question
from quiz.models.trainer import Trainer, TrainerQuestion


class TrainerRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_all_trainers(self) -> list[TrainerRepositoryDTO]:
        """Все тренажёры"""
        trainers = self._session.query(Trainer).all()
        return [
            TrainerRepositoryDTO(
                id=trainer.id,
                guid=trainer.guid,
                name=trainer.name,
                topic_id=trainer.topic_id,
            )
            for trainer in trainers
        ]

    def get_trainer_with_questions(self, trainer_id: int) -> tuple[TrainerRepositoryDTO, list[QuestionRepositoryDTO]]:
        """Тренажёр с его вопросами"""
        trainer = self._session.query(Trainer).filter(Trainer.id == trainer_id).first()
        if not trainer:
            return None, []

        questions = (
            self._session.query(Question)
            .join(TrainerQuestion, Question.id == TrainerQuestion.question_id)
            .filter(TrainerQuestion.trainer_id == trainer_id)
            .all()
        )

        trainer_dto = TrainerRepositoryDTO(
            id=trainer.id,
            guid=trainer.guid,
            name=trainer.name,
            topic_id=trainer.topic_id,
        )

        question_dtos = [QuestionRepositoryDTO.custom(q) for q in questions]
        return trainer_dto, question_dtos

    def get_all_trainers_with_question_counts(
        self,
    ) -> list[tuple[TrainerRepositoryDTO, int]]:
        """Все тренажёры с количеством вопросов"""
        query = (
            self._session.query(Trainer, func.count(TrainerQuestion.question_id))
            .outerjoin(TrainerQuestion, Trainer.id == TrainerQuestion.trainer_id)
            .group_by(Trainer.id)
        )

        result = []
        for trainer, question_count in query.all():
            trainer_dto = TrainerRepositoryDTO(
                id=trainer.id,
                guid=trainer.guid,
                name=trainer.name,
                topic_id=trainer.topic_id,
            )
            result.append((trainer_dto, question_count))
        return result

    def count_questions_by_trainer(self, trainer_id: int) -> int:
        """Количество вопросов в тренажёре"""
        return self._session.query(TrainerQuestion).filter_by(trainer_id=trainer_id).count()

    def get_trainers_by_topic_id(self, topic_id: int) -> list[TrainerRepositoryDTO]:
        """Тренажёры по topic_id"""
        trainers = self._session.query(Trainer).filter_by(topic_id=topic_id).all()
        return [
            TrainerRepositoryDTO(
                id=trainer.id,
                guid=trainer.guid,
                name=trainer.name,
                topic_id=trainer.topic_id,
            )
            for trainer in trainers
        ]

    def get_by_id(self, trainer_id: int) -> TrainerRepositoryDTO | None:
        """Получить тренажёр по ID"""
        trainer = self._session.query(Trainer).filter(Trainer.id == trainer_id).first()
        if trainer:
            return TrainerRepositoryDTO(
                id=trainer.id,
                guid=trainer.guid,
                name=trainer.name,
                topic_id=trainer.topic_id,
            )
        return None

    def create(self, trainer_create) -> TrainerRepositoryDTO:
        """Создать тренажёр"""
        trainer = Trainer(name=trainer_create.name, topic_id=trainer_create.topic_id)
        self._session.add(trainer)
        self._session.flush()
        return TrainerRepositoryDTO(
            id=trainer.id,
            guid=trainer.guid,
            name=trainer.name,
            topic_id=trainer.topic_id,
        )

    def update(self, trainer_id: int, trainer_update) -> TrainerRepositoryDTO:
        """Обновить тренажёр"""
        trainer = self._session.query(Trainer).filter(Trainer.id == trainer_id).first()
        if not trainer:
            return None

        if trainer_update.name:
            trainer.name = trainer_update.name
        if trainer_update.topic_id:
            trainer.topic_id = trainer_update.topic_id

        self._session.flush()
        return TrainerRepositoryDTO(
            id=trainer.id,
            guid=trainer.guid,
            name=trainer.name,
            topic_id=trainer.topic_id,
        )

    def delete(self, trainer_id: int) -> None:
        """Удалить тренажёр"""
        trainer = self._session.query(Trainer).filter(Trainer.id == trainer_id).first()
        if trainer:
            self._session.delete(trainer)

    def add_question_to_trainer(self, trainer_id: int, question_id: int) -> None:
        """Добавить вопрос в тренажёр"""
        trainer_question = TrainerQuestion(trainer_id=trainer_id, question_id=question_id)
        self._session.add(trainer_question)

    def remove_question_from_trainer(self, trainer_id: int, question_id: int) -> None:
        """Удалить вопрос из тренажёра"""
        self._session.query(TrainerQuestion).filter(
            TrainerQuestion.trainer_id == trainer_id,
            TrainerQuestion.question_id == question_id,
        ).delete()

    def get_questions_by_trainer(self, trainer_id: int) -> list[QuestionRepositoryDTO]:
        """Получить вопросы тренажёра"""
        questions = (
            self._session.query(Question)
            .join(TrainerQuestion, Question.id == TrainerQuestion.question_id)
            .filter(TrainerQuestion.trainer_id == trainer_id)
            .all()
        )

        return [QuestionRepositoryDTO.custom(q) for q in questions]

    def get_or_create_by_topic(self, topic_id: int, trainer_name: str) -> TrainerRepositoryDTO:
        """Get or create trainer for topic"""
        trainer = self._session.query(Trainer).filter_by(topic_id=topic_id).first()

        if not trainer:
            trainer = Trainer(name=trainer_name, topic_id=topic_id)
            self._session.add(trainer)
            self._session.flush()

        return TrainerRepositoryDTO(
            id=trainer.id,
            guid=trainer.guid,
            name=trainer.name,
            topic_id=trainer.topic_id,
        )

    def get_by_topic_id(self, topic_id: int) -> TrainerRepositoryDTO | None:
        """Получить тренажёр по topic_id"""
        trainer = self._session.query(Trainer).filter_by(topic_id=topic_id).first()
        if trainer:
            return TrainerRepositoryDTO(
                id=trainer.id,
                guid=trainer.guid,
                name=trainer.name,
                topic_id=trainer.topic_id,
            )
        return None

    def get_trainer_questions(self, trainer_id: int) -> list[Question]:
        """Получить вопросы тренажёра (для обратной совместимости)"""
        return (
            self._session.query(Question)
            .join(TrainerQuestion, Question.id == TrainerQuestion.question_id)
            .filter(TrainerQuestion.trainer_id == trainer_id)
            .all()
        )

    def count_by_topic(self, topic_id: int) -> int:
        """Подсчитать количество тренажёров по теме"""
        return self._session.query(Trainer).filter_by(topic_id=topic_id).count()

    def get_all_trainers_with_detailed_counts(
        self,
    ) -> list[tuple[TrainerRepositoryDTO, int]]:
        """Все тренажёры с количеством вопросов за 1 запрос"""
        stmt = (
            select(Trainer, func.count(TrainerQuestion.question_id).label("question_count"))
            .select_from(Trainer)
            .outerjoin(TrainerQuestion, Trainer.id == TrainerQuestion.trainer_id)
            .group_by(Trainer.id)
        )

        result = self._session.execute(stmt).all()

        return [
            (
                TrainerRepositoryDTO(
                    id=trainer.id,
                    guid=trainer.guid,
                    name=trainer.name,
                    topic_id=trainer.topic_id,
                ),
                question_count or 0,
            )
            for trainer, question_count in result
        ]

    def has_question(self, trainer_id: int, question_id: int) -> bool:
        """Проверить, есть ли связь между тренажером и вопросом"""
        return (
            self._session.query(TrainerQuestion).filter_by(trainer_id=trainer_id, question_id=question_id).first()
            is not None
        )
