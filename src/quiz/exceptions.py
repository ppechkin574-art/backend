class QuestionRepoError(Exception):
    """Errors for question repository and services"""


# class HintRepoNotFound(QuestionRepoError):
#     """When hint not found in database"""


class TopicRepoNotFound(QuestionRepoError):
    """When topic not found in database"""


class QuestionServiceError(Exception):
    """Errors for question service"""


class QuestionNotFound(QuestionServiceError):
    """When question not found in database"""


class HintNotFound(QuestionServiceError):
    """When hint not found in repository"""


class TopicNotFound(QuestionServiceError):
    """When topic not found in repository"""


class ImageNotSavedError(QuestionServiceError):
    """When image failed to save"""


class QuizError(Exception):
    """Class of quiz errors that occurs in quiz test attempt pass service"""


class WrongStudent(QuizError):
    """When wrong student tries to manipulate with test attempt"""


class AlreadyAnswered(QuizError):
    """When answer to test attempt question is already answered"""


class AttemptCompleted(QuizError):
    """When attempt is already completed"""


class AttemptNotCompleted(QuizError):
    """When attempt is not completed"""


class TestQuestionNotExist(QuizError):
    """When answering test attempt question not exist in database"""


class DeadlineExceeded(QuizError):
    """When deadline is exceeded and cannot answer on test attempt"""


class VariantNotExist(QuizError):
    """When given variant does not exist in question"""


class TrainerAttemptNotExist(QuizError):
    """When test attempt not exist in database"""


class TrainerNotFound(QuizError):
    """When trainer attempt not exist"""


class ImportServiceError(Exception):
    """Import error class for importing services"""


class MissingColumns(ImportServiceError):
    """Missing required columns for models import"""


class InvalidFormat(ImportServiceError):
    """If importing of file is in incorrect formatting"""


class InvalidImportData(ImportServiceError):
    """When data is failed to save to DB"""


class NoQuestionsInTrainerAttempt(QuizError):
    """When test attempt questions is empty"""


class SubjectNotFound(Exception):
    """When subject not found in repository"""


class SubjectServiceError(Exception):
    """Errors of subject service"""


class SubjectIntegrityErrorService(Exception):
    """When subject integrity error in repository"""


class SubjectNotFoundService(SubjectServiceError):
    """When subject not found in repository"""


class SubjectIdViolatesNotNullService(SubjectServiceError):
    """When changing or deletion of subject violates constraints"""


class SubjectRepositoryError(Exception):
    """Errors of subject repository"""


class SubjectIntegrityErrorRepository(Exception):
    """When update or creating subject have integrity issues"""


class SubjectNotFoundRepository(SubjectRepositoryError):
    """When subject not found in database"""


class SubjectIdViolatesNotNullRepository(SubjectRepositoryError):
    """When subject deletion or changing id violates some entities in database"""


class TopicServiceError(Exception):
    """Errors of topic service"""


class TopicNotFoundService(TopicServiceError):
    """When topic not found in repository"""


class TopicSubjectNotFoundService(TopicServiceError):
    """When topic's subject not found in database"""


# class TopicSameNameService(TopicServiceError):
#     """When topic integrity error in repository"""


class TopicIdViolatesNotNullService(TopicServiceError):
    """When topic deletion or changing id violates some entities in repository"""


class TopicRepositoryError(Exception):
    """Errors of topic repository"""


class TopicNotFoundRepository(TopicRepositoryError):
    """When topic not found in database"""


class TopicSubjectNotFoundRepository(TopicRepositoryError):
    """When topic's subject not found in database"""


class TopicIdViolatesNotNullRepository(TopicRepositoryError):
    """When topic deletion or changing id violates some entities in database"""


class StatisticDoesNotExist(Exception):
    """When no data for statistic"""


# class TrainerAttemptQuestionNotFound(Exception):
#     """When test attempt question not found"""


class EntOptionsDoesntExist(Exception):
    """When ent options doesnt exist"""


class TestTypeDontImport(Exception):
    """When try import rated and unrated question types"""


class EntOptionAlreadyExist(Exception):
    """when ent already exist"""


class TopicAlreadyExists(Exception):
    """Исключение когда тема с таким именем уже существует в предмете"""

    def __init__(
        self,
        message="Topic with this name already exists in subject",
        existing_topic_id=None,
    ):
        self.message = message
        self.existing_topic_id = existing_topic_id
        super().__init__(self.message)


class TopicSameNameRepository(TopicAlreadyExists):
    """When topic integrity error in database"""


class TopicSameNameService(TopicAlreadyExists):
    """When topic integrity error in repository"""


class SubjectAlreadyExists(Exception):
    """Исключение когда предмет с таким именем уже существует"""

    def __init__(self, message="Subject with this name already exists", existing_subject_id=None):
        self.message = message
        self.existing_subject_id = existing_subject_id
        super().__init__(self.message)


class SubjectSameNameRepository(SubjectAlreadyExists):
    """When subject integrity error in repository"""


class SubjectSameNameService(SubjectAlreadyExists):
    """When subject integrity error in service"""


class TopicsMergeError(ValueError):
    """Ошибка слияния тем"""


class SubjectModuleNotFoundRepository(Exception):
    """Module not found in repository"""


class SubjectModuleNotFoundService(Exception):
    """Module not found in service"""


class ModuleLessonNotFoundRepository(Exception):
    """Lesson not found in repository"""


class ModuleLessonNotFoundService(Exception):
    """Lesson not found in service"""


class LessonTestNotFoundRepository(Exception):
    """Lesson test not found in repository"""


# class LessonTestNotFoundService(Exception):
#     """Lesson test not found in service"""


class ModuleTestNotFoundRepository(Exception):
    """Module test not found in repository"""


class ModuleTestNotFoundService(Exception):
    """Module test not found in service"""


class ModuleIntegrityErrorRepository(Exception):
    """Module integrity error in repository"""


class ModuleIntegrityErrorService(Exception):
    """Module integrity error in service"""


class ModuleSameNameRepository(Exception):
    """Module with same name already exists"""

    def __init__(self, message: str, existing_module_id: int):
        super().__init__(message)
        self.existing_module_id = existing_module_id


class ModuleSameNameService(Exception):
    """Module with same name already exists in service"""

    def __init__(self, message: str, existing_module_id: int = None):
        super().__init__(message)
        self.existing_module_id = existing_module_id


class LessonIntegrityErrorRepository(Exception):
    """Lesson integrity error in repository"""


class LessonIntegrityErrorService(Exception):
    """Lesson integrity error in service"""


class LessonSameNameRepository(Exception):
    """Lesson with same name already exists in module"""

    def __init__(self, message: str, existing_lesson_id: int):
        super().__init__(message)
        self.existing_lesson_id = existing_lesson_id


class LessonSameNameService(Exception):
    """Lesson with same name already exists in module"""

    def __init__(self, message: str, existing_lesson_id: int = None):
        super().__init__(message)
        self.existing_lesson_id = existing_lesson_id


class ModuleIdViolatesNotNullRepository(Exception):
    """Cannot delete module due to foreign key constraints"""


class ModuleIdViolatesNotNullService(Exception):
    """Cannot delete module due to foreign key constraints"""


class LessonIdViolatesNotNullRepository(Exception):
    """Cannot delete lesson due to foreign key constraints"""


class LessonIdViolatesNotNullService(Exception):
    """Cannot delete lesson due to foreign key constraints"""


class ModuleOrderUpdateError(Exception):
    """Ошибка обновления порядка модулей"""


class LessonOrderUpdateError(Exception):
    """Ошибка обновления порядка уроков"""


# class TestNotFoundError(Exception):
#     """Тест не найден"""


class QuestionNotFoundError(Exception):
    """Вопрос не найден"""


class TestQuestionAlreadyExistsError(Exception):
    """Вопрос уже добавлен в тест"""


# class InvalidQuestionError(Exception):
#     """Некорректный вопрос"""


# class LessonAlreadyPublishedError(Exception):
#     """Урок уже опубликован"""


class LessonNotPublishedError(Exception):
    """Урок не опубликован"""
