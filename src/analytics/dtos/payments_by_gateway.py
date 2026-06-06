from decimal import Decimal

from pydantic import BaseModel


class PaymentByGatewayRowDTO(BaseModel):
    """Paid-payment totals for one gateway (google_play vs freedompay)."""

    gateway: str
    count: int
    total_amount: Decimal


class PaymentsByGatewaySummaryDTO(BaseModel):
    window_hours: int
    total_amount: Decimal
    rows: list[PaymentByGatewayRowDTO]
