from sqlalchemy.orm import declarative_base

from database.database import Database
from database.settings import DatabaseSettings

Base = declarative_base()

__all__ = ["Base", "Database", "DatabaseSettings"]
