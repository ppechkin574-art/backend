# from typing import Protocol

# from sqlalchemy.orm import Session

# from student.models import LastRatedTrainerAttemptId


# # class LastTrainerAttemptIdRepositoryInterface(Protocol):
# #     def get(self) -> int:
# #         """
# #         Get last test attempt id

# #         Returns:
# #             Last rated test attempt id (int).
# #         """
# #         raise NotImplementedError

# #     def set(self, test_attempt_id: int) -> None:
# #         """
# #         Set last test attempt id
# #         """


# # class LastTrainerAttemptIdRepository:
# #     def __init__(self, session: Session):
# #         self._session = session

# #     def get(self) -> int:
# #         last_id = self._session.query(LastRatedTrainerAttemptId).first()
# #         return last_id.test_attempt_id if last_id is not None else 0

# #     def set(self, test_attempt_id: int) -> None:
# #         record = self._session.query(LastRatedTrainerAttemptId).first()
# #         if record:
# #             record.test_attempt_id = test_attempt_id
# #         else:
# #             self._session.add(LastRatedTrainerAttemptId(test_attempt_id=test_attempt_id))
