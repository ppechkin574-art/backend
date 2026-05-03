# from typing import Protocol

# from student.dtos.rating import RatingAnswerDTO, RatingQuestionDTO
# from student.uows.rating import UnitOfWorkLastTrainerAttemptId


# class RatingServiceInterface(Protocol):
#     def calculate(self, rating_question: RatingQuestionDTO, answers: list[RatingAnswerDTO]) -> int:
#         """
#         Calculate student add rating on not proceed test attempts.

#         Args:
#             rating_question (RatingQuestionDTO): rating question
#             answers (list[RatingAnswerDTO]): answers
#         """
#         raise NotImplementedError

#     def get_last_calculated_id(self) -> int:
#         """
#         Get last calculated test attempt id from saved table value.

#         Returns:r
#             Last calculated test attempt id, if not found when return 0
#         """

#     def set_last_calculated_id(self, last_calculated_id: int) -> None:
#         """
#         Set last calculated test attempt id into saved table value.
#         """


# class RatingService:
#     def __init__(self, uow_last_test_attempt_id: UnitOfWorkLastTrainerAttemptId):
#         self.uow_last_test_attempt_id = uow_last_test_attempt_id

#     def calculate(self, rating_question: RatingQuestionDTO, answers: list[RatingAnswerDTO]) -> int:
#         rating = 0
#         for answer in answers:
#             rating += (2 * int(answer.is_correct) - 1) * rating_question.weight
#         return rating

#     def get_last_calculated_id(self) -> int:
#         with self.uow_last_test_attempt_id:
#             last_id = self.uow_last_test_attempt_id.last_test_attempt_id.get()
#             return last_id if last_id is not None else 0

#     def set_last_calculated_id(self, last_calculated_id: int) -> None:
#         with self.uow_last_test_attempt_id:
#             return self.uow_last_test_attempt_id.last_test_attempt_id.set(last_calculated_id)
