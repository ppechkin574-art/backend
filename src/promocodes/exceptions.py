from fastapi import HTTPException, status


class PromocodeError(HTTPException):
    """Base exception for promocode-related errors."""

    pass


class PromocodeActivationError(PromocodeError):
    def __init__(self, detail: str = "Error activating promocode"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class PromocodeNotFoundError(PromocodeError):
    def __init__(self, detail: str = "Promocode not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class PromocodeExpiredError(PromocodeError):
    def __init__(self, detail: str = "Promocode has expired"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class PromocodeAlreadyUsedError(PromocodeError):
    def __init__(self, detail: str = "Promocode has already been used"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class PromocodeInvalidError(PromocodeError):
    def __init__(self, detail: str = "Invalid promocode"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
