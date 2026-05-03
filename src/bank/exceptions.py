class BankError(Exception):
    """Base exception for bank-related errors."""

    pass


class CardStyleNotFound(BankError):
    """Style not found."""

    pass


class BankAccountNotFound(BankError):
    """Account not found."""

    pass


class InsufficientBalance(BankError):
    """Insufficient balance."""

    pass


class WithdrawalAmountTooSmall(BankError):
    """Withdrawal amount too small."""

    pass


class WithdrawalRequestNotFound(BankError):
    """Withdrawal request not found."""

    pass


class TransactionNotFound(BankError):
    """Transaction not found."""

    pass


class InvalidWithdrawalStatus(BankError):
    """Invalid withdrawal status."""

    pass
