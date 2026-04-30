# backend\src\quiz\repositories\progress.py
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from quiz.models.edu_content import Question, Subject, Topic
from quiz.models.progress import UserQuestionProgress


class ProgressRepository:
    def __init__(self, session: Session):
        self._session = session

    def record_progress(
        self,
        user_id: str,
        question_id: int,
        is_correct: bool,
        attempt_type: str,
        attempt_id: int,
    ) -> None:
        """Записать прогресс пользователя по вопросу"""
        existing = self._session.execute(
            select(UserQuestionProgress).where(
                and_(
                    UserQuestionProgress.user_id == user_id,
                    UserQuestionProgress.question_id == question_id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            # Обновляем только если новый результат лучше (правильный вместо неправильного)
            if is_correct and not existing.is_correct:
                existing.is_correct = is_correct
                existing.attempt_type = attempt_type
                existing.attempt_id = attempt_id
                self._session.add(existing)
        else:
            progress = UserQuestionProgress(
                user_id=user_id,
                question_id=question_id,
                is_correct=is_correct,
                attempt_type=attempt_type,
                attempt_id=attempt_id,
            )
            self._session.add(progress)

    def get_topic_progress(self, user_id: str, topic_id: int, only_correct: bool = True) -> float:
        """Получить прогресс по теме как число от 0 до 1"""
        # Статистика по теме
        stmt = (
            select(
                func.count(Question.id).label("total_questions"),
                func.count(
                    case(
                        (
                            and_(
                                UserQuestionProgress.user_id == user_id,
                                UserQuestionProgress.question_id == Question.id,
                                (UserQuestionProgress.is_correct if only_correct else True),
                            ),
                            1,
                        )
                    )
                ).label("solved_questions"),
            )
            .select_from(Question)
            .where(Question.topic_id == topic_id)
            .outerjoin(
                UserQuestionProgress,
                and_(
                    UserQuestionProgress.question_id == Question.id,
                    UserQuestionProgress.user_id == user_id,
                ),
            )
        )

        result = self._session.execute(stmt).first()

        total_questions = result.total_questions or 0
        solved_questions = result.solved_questions or 0

        # Возвращаем прогресс как число от 0 до 1
        return solved_questions / total_questions if total_questions > 0 else 0.0

    def get_subject_progress(self, user_id: str, subject_id: int, only_correct: bool = True) -> float:
        """Получить прогресс по предмету как число от 0 до 1 (среднее по темам)"""
        # Получаем все темы предмета
        topics = self._session.execute(select(Topic).where(Topic.subject_id == subject_id)).scalars().all()

        if not topics:
            return 0.0

        # Собираем прогресс по каждой теме
        topic_progresses = []
        for topic in topics:
            progress = self.get_topic_progress(user_id, topic.id, only_correct)
            topic_progresses.append(progress)

        # Средний прогресс по темам
        return sum(topic_progresses) / len(topic_progresses) if topic_progresses else 0.0

    def get_topics_with_progress_by_subject(
        self, user_id: str, subject_id: int, only_correct: bool = True
    ) -> list[dict]:
        """Получить все темы предмета с прогрессом"""
        topics = self._session.execute(select(Topic).where(Topic.subject_id == subject_id)).scalars().all()

        result = []
        for topic in topics:
            progress = self.get_topic_progress(user_id, topic.id, only_correct)
            result.append(
                {
                    "id": topic.id,
                    "name": topic.name,
                    "subject_id": topic.subject_id,
                    "progress": progress,
                }
            )

        return result

    def get_subjects_with_progress(self, user_id: str, only_correct: bool = True) -> list[dict]:
        """Получить все предметы с прогрессом"""
        subjects = self._session.execute(select(Subject)).scalars().all()

        result = []
        for subject in subjects:
            progress = self.get_subject_progress(user_id, subject.id, only_correct)
            result.append(
                {
                    "id": subject.id,
                    "name": subject.name,
                    "type": subject.type,
                    "image": subject.image,
                    "progress": progress,
                }
            )

        return result
