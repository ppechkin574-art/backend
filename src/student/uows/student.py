from database.uows import UnitOfWorkSQLAlchemy
from student.repositories import StudentsRepository, StudentsRepositoryInterface


class UnitOfWorkStudents(UnitOfWorkSQLAlchemy):
    def __enter__(self):
        super().__enter__()
        self.students: StudentsRepositoryInterface = StudentsRepository(self.session)
        return self
