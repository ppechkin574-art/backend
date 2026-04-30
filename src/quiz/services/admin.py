import logging

from quiz.dtos.admin import (
    AdminDashboardDTO,
    AdminEntOptionDTO,
    AdminSubjectDTO,
    AdminTopicDTO,
    AdminTrainerDTO,
)
from quiz.services.ent_options import EntOptionServiceInterface
from quiz.services.questions import QuestionServiceInterface
from quiz.services.subjects import SubjectServiceInterface
from quiz.services.topics import TopicServiceInterface
from quiz.services.trainers import TrainerServiceInterface

logger = logging.getLogger(__name__)


class AdminService:
    def __init__(
        self,
        question_service: QuestionServiceInterface,
        subject_service: SubjectServiceInterface,
        topic_service: TopicServiceInterface,
        trainer_service: TrainerServiceInterface,
        ent_option_service: EntOptionServiceInterface,
    ):
        self.question_service = question_service
        self.subject_service = subject_service
        self.topic_service = topic_service
        self.trainer_service = trainer_service
        self.ent_option_service = ent_option_service

    def get_admin_dashboard(self) -> AdminDashboardDTO:
        """Получить все данные для админской панели за минимальное количество запросов"""

        subjects = self.subject_service.get_all_subjects_with_detailed_info()
        topics = self.topic_service.get_all_topics_with_detailed_info()
        trainers = self.trainer_service.get_all_trainers_with_detailed_info()
        ent_options = self.ent_option_service.get_all_ent_options_with_counts()

        self._link_data(subjects, topics, trainers)

        total_stats = self._get_total_stats(subjects, topics, trainers, ent_options)

        return AdminDashboardDTO(
            subjects=subjects,
            topics=topics,
            trainers=trainers,
            ent_options=ent_options,
            total_stats=total_stats,
        )

    def _link_data(
        self,
        subjects: list[AdminSubjectDTO],
        topics: list[AdminTopicDTO],
        trainers: list[AdminTrainerDTO],
    ):
        """Связать данные между сущностями"""

        topics_by_subject = {}
        for topic in topics:
            if topic.subject_id not in topics_by_subject:
                topics_by_subject[topic.subject_id] = []
            topics_by_subject[topic.subject_id].append(topic)

        trainers_by_topic = {}
        for trainer in trainers:
            if trainer.topic_id not in trainers_by_topic:
                trainers_by_topic[trainer.topic_id] = []
            trainers_by_topic[trainer.topic_id].append(trainer)

        for subject in subjects:
            subject.topics = topics_by_subject.get(subject.id, [])

        for topic in topics:
            topic.trainers = trainers_by_topic.get(topic.id, [])

    def _get_total_stats(
        self,
        subjects: list[AdminSubjectDTO],
        topics: list[AdminTopicDTO],
        trainers: list[AdminTrainerDTO],
        ent_options: list[AdminEntOptionDTO],
    ) -> dict[str, int]:
        """Получить общую статистику"""

        total_subjects = len(subjects)
        total_topics = len(topics)
        total_trainers = len(trainers)
        total_ent_options = len(ent_options)

        _, total_questions = self.question_service.list(
            page=1,
            page_size=1,
        )
        total_questions_in_trainers = sum(trainer.question_count for trainer in trainers)
        total_questions_in_ent = sum(option.question_count for option in ent_options)

        return {
            "total_subjects": total_subjects,
            "total_topics": total_topics,
            "total_trainers": total_trainers,
            "total_ent_options": total_ent_options,
            "total_questions": total_questions,
            "total_questions_in_trainers": total_questions_in_trainers,
            "total_questions_in_ent": total_questions_in_ent,
        }
