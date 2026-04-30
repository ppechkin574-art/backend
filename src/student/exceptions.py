class StudentError(Exception):
    """Exceptions for student layer"""


class StudentNotFound(StudentError):
    """When student not found in database"""


# class RatingError(Exception):
#     """Exceptions for rating layer"""


# class InvalidDifficulty(RatingError):
#     """When difficulty is not converted to weight"""

#     def __init__(self, difficulty: str):
#         self.difficulty = difficulty
#         super().__init__(f"Invalid difficulty: {difficulty}")
