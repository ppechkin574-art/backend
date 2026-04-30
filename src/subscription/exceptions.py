from fastapi import HTTPException, status


class SubscriptionError(HTTPException):
    """Base exception for subscription-related errors."""

    pass


class SubscriptionRequired(SubscriptionError):
    def __init__(self, detail: str = "Subscription required"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class InsufficientPlanError(SubscriptionError):
    def __init__(self, detail: str = "Insufficient subscription plan"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
