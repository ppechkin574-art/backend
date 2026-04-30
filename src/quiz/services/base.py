from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T")
CreateDTO = TypeVar("CreateDTO", bound=BaseModel)
UpdateDTO = TypeVar("UpdateDTO", bound=BaseModel)
ServiceDTO = TypeVar("ServiceDTO", bound=BaseModel)
RepositoryDTO = TypeVar("RepositoryDTO", bound=BaseModel)
QuestionCreateDTO = TypeVar("QuestionCreateDTO", bound=BaseModel)
QuestionUpdateDTO = TypeVar("QuestionUpdateDTO", bound=BaseModel)
QuestionServiceDTO = TypeVar("QuestionServiceDTO", bound=BaseModel)


class BaseServiceInterface[CreateDTO: BaseModel, UpdateDTO: BaseModel, ServiceDTO: BaseModel](ABC):
    """Base interface for all services with standard CRUD operations"""

    @abstractmethod
    def create(self, create_dto: CreateDTO) -> ServiceDTO:
        """Create a new entity"""
        pass

    @abstractmethod
    def get_by_id(self, entity_id: int) -> ServiceDTO:
        """Get entity by ID"""
        pass

    @abstractmethod
    def update(self, entity_id: int, update_dto: UpdateDTO) -> ServiceDTO:
        """Update entity by ID"""
        pass

    @abstractmethod
    def delete(self, entity_id: int) -> None:
        """Delete entity by ID"""
        pass

    @abstractmethod
    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
    ) -> tuple[list[ServiceDTO], int]:
        """Get paginated list of entities with filtering and sorting"""
        pass


class BaseRepositoryInterface[CreateDTO: BaseModel, UpdateDTO: BaseModel, RepositoryDTO: BaseModel](ABC):
    """Base interface for all repositories with standard CRUD operations"""

    @abstractmethod
    def create(self, create_dto: CreateDTO) -> RepositoryDTO:
        """Create a new entity in database"""
        pass

    @abstractmethod
    def get_by_id(self, entity_id: int) -> RepositoryDTO:
        """Get entity by ID from database"""
        pass

    @abstractmethod
    def update(self, entity_id: int, update_dto: UpdateDTO) -> RepositoryDTO:
        """Update entity by ID in database"""
        pass

    @abstractmethod
    def delete(self, entity_id: int) -> None:
        """Delete entity by ID from database"""
        pass

    @abstractmethod
    def list(
        self,
        offset: int,
        limit: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[RepositoryDTO], int]:
        """Get paginated list of entities from database"""
        pass
