from bank.repository import BankRepository
from database.uows import UnitOfWorkSQLAlchemy
from quiz.repositories.attendance import AttendanceRepository
from quiz.repositories.cashback import CashbackRepository
from quiz.repositories.daily_tests import DailyTestRepository
from quiz.repositories.ent_attempts import (
    EntAttemptRepository,
    EntAttemptRepositoryInterface,
)
from quiz.repositories.ent_options import (
    EntOptionRepository,
    EntOptionsRepositoryInterface,
)
from quiz.repositories.ent_questions import (
    EntOptionQuestionRepository,
    EntOptionQuestionRepositoryInterface,
)
from quiz.repositories.modules import (
    LessonTestRepository,
    ModuleLessonRepository,
    ModuleTestRepository,
    SubjectModuleRepository,
)
from quiz.repositories.modules_progress import (
    UserLessonProgressRepository,
    UserModuleProgressRepository,
)
from quiz.repositories.progress import ProgressRepository
from quiz.repositories.questions import QuestionRepository, QuestionRepositoryInterface
from quiz.repositories.subjects import SubjectRepository, SubjectRepositoryInterface
from quiz.repositories.topics import TopicRepository, TopicRepositoryInterface
from quiz.repositories.trainer_attempts import (
    TrainerAttemptRepository,
    TrainerAttemptRepositoryInterface,
)
from quiz.repositories.trainers import TrainerRepository


class UnitOfWorkTests(UnitOfWorkSQLAlchemy):
    def __enter__(self):
        super().__enter__()
        self.questions: QuestionRepositoryInterface = QuestionRepository(self.session)
        self.subjects: SubjectRepositoryInterface = SubjectRepository(self.session)
        self.topics: TopicRepositoryInterface = TopicRepository(self.session)
        self.ent_options: EntOptionsRepositoryInterface = EntOptionRepository(self.session)
        self.ent_questions: EntOptionQuestionRepositoryInterface = EntOptionQuestionRepository(self.session)
        self.ent_attempts: EntAttemptRepositoryInterface = EntAttemptRepository(self.session)
        self.trainers: TrainerRepository = TrainerRepository(self.session)
        self.trainer_attempts: TrainerAttemptRepositoryInterface = TrainerAttemptRepository(self.session)
        self.progress = ProgressRepository(self.session)
        self.daily_tests: DailyTestRepository = DailyTestRepository(self.session)
        self.attendance: AttendanceRepository = AttendanceRepository(self.session)
        self.subject_modules = SubjectModuleRepository(self.session)
        self.module_lessons = ModuleLessonRepository(self.session)
        self.lesson_tests = LessonTestRepository(self.session)
        self.module_tests = ModuleTestRepository(self.session)
        self.user_lesson_progress = UserLessonProgressRepository(self.session)
        self.user_module_progress = UserModuleProgressRepository(self.session)
        self.cashback = CashbackRepository(self.session)
        self.bank = BankRepository(self.session)
        return self


class UnitOfWorkQuestions(UnitOfWorkSQLAlchemy):
    def __enter__(self):
        super().__enter__()
        self.questions: QuestionRepositoryInterface = QuestionRepository(self.session)
        self.subjects: SubjectRepositoryInterface = SubjectRepository(self.session)
        self.topics: TopicRepositoryInterface = TopicRepository(self.session)
        self.ent_options: EntOptionsRepositoryInterface = EntOptionRepository(self.session)
        self.ent_questions: EntOptionQuestionRepositoryInterface = EntOptionQuestionRepository(self.session)
        self.ent_attempts: EntAttemptRepositoryInterface = EntAttemptRepository(self.session)
        self.trainers: TrainerRepository = TrainerRepository(self.session)
        self.trainer_attempts: TrainerAttemptRepositoryInterface = TrainerAttemptRepository(self.session)
        self.progress = ProgressRepository(self.session)
        self.daily_tests: DailyTestRepository = DailyTestRepository(self.session)
        self.attendance: AttendanceRepository = AttendanceRepository(self.session)
        return self
