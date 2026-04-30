from database import Database


class UnitOfWorkSQLAlchemy:
    def __init__(self, db: Database):
        self._db = db
        self.session = None

    def __enter__(self):
        self.session = self._db.session
        return self

    def __exit__(self, *args):
        if any(args):
            self.rollback()
        else:
            self.commit()
        self.session.close()

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()
