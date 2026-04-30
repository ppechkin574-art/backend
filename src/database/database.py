from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from database.settings import DatabaseSettings


class Database:
    def __init__(self, settings: DatabaseSettings):
        _engine = create_engine(settings.uri, echo=False, pool_pre_ping=True)
        self._session_maker = sessionmaker(bind=_engine, autocommit=False, autoflush=False)

    @property
    def session(self) -> Session:
        return self._session_maker()
