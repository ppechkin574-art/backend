from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session

from student.dtos import StudentDTO
from student.dtos.student import StudentCreateDTO
from student.exceptions import StudentNotFound
from student.models import Student


class StudentsRepositoryInterface(Protocol):
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
            student_id (UUID): id the student.
            delta (int): adding to rating value.

        Raises:
            StudentNotFound
        """
        raise NotImplementedError


class StudentsRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_or_create(self, student_id: UUID) -> StudentDTO:
        query = self._session.query(Student).filter_by(id=student_id)
        try:
            return StudentDTO.model_validate(query.one())
        except NoResultFound:
            pass

        student = StudentCreateDTO(id=student_id)
        self._session.add(Student(**student.model_dump()))
        try:
            self._session.flush()
        except IntegrityError:
            self._session.rollback()
            return StudentDTO.model_validate(query.one())

        return StudentDTO.model_validate(student)

    def add_rating(self, student_id: UUID, delta: int) -> None:
        student = self._session.query(Student).get(student_id)
        if not student:
            raise StudentNotFound
        student.rating += delta
