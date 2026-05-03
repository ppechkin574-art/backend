from typing import Protocol


class UnitOfWorkInterface(Protocol):
    def __enter__(self):
        raise NotImplementedError

    def __exit__(self, *args):
        raise NotImplementedError

    def commit(self):
        raise NotImplementedError

    def rollback(self):
        raise NotImplementedError
