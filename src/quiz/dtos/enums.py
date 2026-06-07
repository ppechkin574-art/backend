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


class DraftStatus(Enum):
    """Lifecycle of an AI-generated question draft in the review pipeline.

    draft     — freshly generated, awaiting human review
    approved  — reviewer OK'd it but hasn't published yet (optional step)
    rejected  — reviewer discarded it; never reaches live `questions`
    published — converted into a live `questions` row (see published_question_id)
    """

    draft = "draft"
    approved = "approved"
    rejected = "rejected"
    published = "published"
