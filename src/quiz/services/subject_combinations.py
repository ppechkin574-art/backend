import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from api.routes.quiz.dtos import (
    SubjectCombinationCreateRequestDTO,
    SubjectCombinationResponseDTO,
    SubjectCombinationUpdateRequestDTO,
)
from quiz.models.edu_content import Subject
from quiz.models.ent import EntSubjectCombination
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger(__name__)


class SubjectCombinationService:
    """Service for managing subject combinations"""

    def __init__(self, session: Session, cache_service: CacheService):
        self._session = session
        self._cache_service = cache_service

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="subject_combinations")
    def get_all(self) -> list[SubjectCombinationResponseDTO]:
        """Get all subject combinations"""
        combinations = self._session.query(EntSubjectCombination).all()

        result = []
        for combo in combinations:
            subj1 = self._session.query(Subject).filter(Subject.id == combo.specialized_subject_1_id).first()
            subj2 = self._session.query(Subject).filter(Subject.id == combo.specialized_subject_2_id).first()

            if subj1 and subj2:
                result.append(
                    SubjectCombinationResponseDTO(
                        id=combo.id,
                        name=combo.name or f"{subj1.name} + {subj2.name}",
                        description=combo.description,
                        specialized_subject_1_id=combo.specialized_subject_1_id,
                        specialized_subject_1_name=subj1.name,
                        specialized_subject_2_id=combo.specialized_subject_2_id,
                        specialized_subject_2_name=subj2.name,
                    )
                )

        return result

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="subject_combination")
    def get_by_id(self, combination_id: int) -> SubjectCombinationResponseDTO:
        """Get subject combination by ID"""
        combo = self._session.query(EntSubjectCombination).filter(EntSubjectCombination.id == combination_id).first()

        if not combo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subject combination with id {combination_id} not found",
            )

        subj1 = self._session.query(Subject).filter(Subject.id == combo.specialized_subject_1_id).first()
        subj2 = self._session.query(Subject).filter(Subject.id == combo.specialized_subject_2_id).first()

        if not subj1 or not subj2:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or both subjects not found",
            )

        return SubjectCombinationResponseDTO(
            id=combo.id,
            name=combo.name or f"{subj1.name} + {subj2.name}",
            description=combo.description,
            specialized_subject_1_id=combo.specialized_subject_1_id,
            specialized_subject_1_name=subj1.name,
            specialized_subject_2_id=combo.specialized_subject_2_id,
            specialized_subject_2_name=subj2.name,
        )

    def create(self, data: SubjectCombinationCreateRequestDTO) -> SubjectCombinationResponseDTO:
        """Create new subject combination"""
        # Validate subjects exist
        subj1 = self._session.query(Subject).filter(Subject.id == data.specialized_subject_1_id).first()
        subj2 = self._session.query(Subject).filter(Subject.id == data.specialized_subject_2_id).first()

        if not subj1:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subject with id {data.specialized_subject_1_id} not found",
            )

        if not subj2:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subject with id {data.specialized_subject_2_id} not found",
            )

        # Validate subjects are different
        if data.specialized_subject_1_id == data.specialized_subject_2_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specialized subjects must be different",
            )

        # Check if combination already exists
        existing = (
            self._session.query(EntSubjectCombination)
            .filter(
                (
                    (EntSubjectCombination.specialized_subject_1_id == data.specialized_subject_1_id)
                    & (EntSubjectCombination.specialized_subject_2_id == data.specialized_subject_2_id)
                )
                | (
                    (EntSubjectCombination.specialized_subject_1_id == data.specialized_subject_2_id)
                    & (EntSubjectCombination.specialized_subject_2_id == data.specialized_subject_1_id)
                )
            )
            .first()
        )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This subject combination already exists",
            )

        # Create combination
        combo = EntSubjectCombination(
            name=data.name,
            description=data.description,
            specialized_subject_1_id=data.specialized_subject_1_id,
            specialized_subject_2_id=data.specialized_subject_2_id,
        )

        self._session.add(combo)
        self._session.commit()
        self._session.refresh(combo)

        logger.info("Created subject combination: %s - %s", combo.id, combo.name)
        self._cache_service.invalidate_by_resource("subject_combinations")
        logger.info("Invalidated subject combinations cache after creation")

        return SubjectCombinationResponseDTO(
            id=combo.id,
            name=combo.name,
            description=combo.description,
            specialized_subject_1_id=combo.specialized_subject_1_id,
            specialized_subject_1_name=subj1.name,
            specialized_subject_2_id=combo.specialized_subject_2_id,
            specialized_subject_2_name=subj2.name,
        )

    def update(self, combination_id: int, data: SubjectCombinationUpdateRequestDTO) -> SubjectCombinationResponseDTO:
        """Update subject combination"""
        combo = self._session.query(EntSubjectCombination).filter(EntSubjectCombination.id == combination_id).first()

        if not combo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subject combination with id {combination_id} not found",
            )

        # Update fields
        if data.name is not None:
            combo.name = data.name

        if data.description is not None:
            combo.description = data.description

        if data.specialized_subject_1_id is not None or data.specialized_subject_2_id is not None:
            # Determine new subject IDs
            new_subj1_id = (
                data.specialized_subject_1_id
                if data.specialized_subject_1_id is not None
                else combo.specialized_subject_1_id
            )
            new_subj2_id = (
                data.specialized_subject_2_id
                if data.specialized_subject_2_id is not None
                else combo.specialized_subject_2_id
            )

            # Validate subjects are different
            if new_subj1_id == new_subj2_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Specialized subjects must be different",
                )

            # Validate subjects exist
            subj1 = self._session.query(Subject).filter(Subject.id == new_subj1_id).first()
            subj2 = self._session.query(Subject).filter(Subject.id == new_subj2_id).first()

            if not subj1:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Subject with id {new_subj1_id} not found",
                )

            if not subj2:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Subject with id {new_subj2_id} not found",
                )

            # Check if combination already exists (excluding current)
            existing = (
                self._session.query(EntSubjectCombination)
                .filter(
                    EntSubjectCombination.id != combination_id,
                    (
                        (
                            (EntSubjectCombination.specialized_subject_1_id == new_subj1_id)
                            & (EntSubjectCombination.specialized_subject_2_id == new_subj2_id)
                        )
                        | (
                            (EntSubjectCombination.specialized_subject_1_id == new_subj2_id)
                            & (EntSubjectCombination.specialized_subject_2_id == new_subj1_id)
                        )
                    ),
                )
                .first()
            )

            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This subject combination already exists",
                )

            combo.specialized_subject_1_id = new_subj1_id
            combo.specialized_subject_2_id = new_subj2_id

        self._session.commit()
        self._session.refresh(combo)

        logger.info("Updated subject combination: %s - %s", combo.id, combo.name)

        # Get subject names for response
        subj1 = self._session.query(Subject).filter(Subject.id == combo.specialized_subject_1_id).first()
        subj2 = self._session.query(Subject).filter(Subject.id == combo.specialized_subject_2_id).first()

        self._cache_service.invalidate_by_resource("subject_combinations")
        self._cache_service.delete(
            self._cache_service.make_key(
                CacheStrategy.GLOBAL,
                resource="subject_combination",
                params=f"id:{combination_id}",
            )
        )
        logger.info("Invalidated subject combination cache after update")

        return SubjectCombinationResponseDTO(
            id=combo.id,
            name=combo.name,
            description=combo.description,
            specialized_subject_1_id=combo.specialized_subject_1_id,
            specialized_subject_1_name=subj1.name,
            specialized_subject_2_id=combo.specialized_subject_2_id,
            specialized_subject_2_name=subj2.name,
        )

    def delete(self, combination_id: int) -> str:
        """Delete subject combination"""
        combo = self._session.query(EntSubjectCombination).filter(EntSubjectCombination.id == combination_id).first()

        if not combo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subject combination with id {combination_id} not found",
            )

        combo_name = combo.name
        self._session.delete(combo)
        self._session.commit()

        logger.info("Deleted subject combination: %s - %s", combination_id, combo_name)
        self._cache_service.invalidate_by_resource("subject_combinations")
        self._cache_service.delete(
            self._cache_service.make_key(
                CacheStrategy.GLOBAL,
                resource="subject_combination",
                params=f"id:{combination_id}",
            )
        )
        logger.info("Invalidated subject combination cache after deletion")

        return f"Subject combination '{combo_name}' deleted successfully"
