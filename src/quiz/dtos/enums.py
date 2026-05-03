from enum import Enum


class QuestionType(Enum):
    single_choice = "single_choice"
    multiple_choice = "multiple_choice"
    matching = "matching"


class TestType(Enum):
    unrated = "unrated"
    rated = "rated"
    ent = "ent"
    training = "training"


class Difficulty(Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class Status(Enum):
    in_progress = "in_progress"
    completed = "completed"


class BlockType(Enum):
    text = "text"
    media = "media"
    video = "video"


class SubjectType(Enum):
    main = "main"
    specialized = "specialized"


class ExamType(Enum):
    by_subject = "by_subject"
    full_exam = "full_exam"
