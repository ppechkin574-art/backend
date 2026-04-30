from analytics.repository import AnalyticRepository, AnalyticRepositoryInterface
from database.uows import UnitOfWorkSQLAlchemy


class UnitOfWorkAnalytics(UnitOfWorkSQLAlchemy):
    def __enter__(self):
        super().__enter__()
        self.anlytic_repo: AnalyticRepositoryInterface = AnalyticRepository(self.session)
        return self
