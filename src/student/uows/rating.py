# from database.uows import UnitOfWorkSQLAlchemy
# from student.repositories.rating import (
#     LastTrainerAttemptIdRepository,
#     LastTrainerAttemptIdRepositoryInterface,
# )


# class UnitOfWorkLastTrainerAttemptId(UnitOfWorkSQLAlchemy):
#     def __enter__(self):
#         super().__enter__()
#         self.last_test_attempt_id: LastTrainerAttemptIdRepositoryInterface = LastTrainerAttemptIdRepository(
#             self.session
#         )
#         return self
