from sqlalchemy import UUID, Column, Integer

from database import Base


class Student(Base):
    __tablename__ = "students"
    id = Column(UUID(as_uuid=True), primary_key=True)
    rating = Column(Integer, nullable=False)


class LastRatedTrainerAttemptId(Base):
    __tablename__ = "last_rated_test_attempt_id"
    test_attempt_id = Column(Integer, primary_key=True)
