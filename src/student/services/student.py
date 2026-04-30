from typing import Protocol
from uuid import UUID

from student.dtos import StudentDTO
from student.exceptions import StudentNotFound
from student.uows import UnitOfWorkStudents


class StudentServiceInterface(Protocol):
    def get_or_create(self, student_id: UUID) -> StudentDTO:
        """
        Get or create student.

        Args:
            student_id: UUID of the student.
        """
        raise NotImplementedError

    def add_rating(self, student_id: UUID, delta: int) -> None:
        """
        Adds delta to student rating.

        Args:
            student_id (UUID): id of the student.
            delta (int): delta to add to rating.

        Raises:
            StudentNotFound
        """
        raise NotImplementedError


class StudentService:
    def __init__(self, uow: UnitOfWorkStudents):
        self._uow = uow

    def get_or_create(self, student_id: UUID) -> StudentDTO:
        with self._uow:
            return self._uow.students.get_or_create(student_id)

    def add_rating(self, student_id: UUID, rating: int) -> None:
        with self._uow:
            try:
                self._uow.students.add_rating(student_id, rating)
            except StudentNotFound:
                raise StudentNotFound
