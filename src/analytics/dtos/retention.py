from pydantic import BaseModel, ConfigDict


class RetentionMonthDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    month_start: str
    registrations: int = 0
    d1: float
    w1: float
    m1: float


class RetentionDTO(BaseModel):
    d1: float
    w1: float
    m1: float

    retention_rate_by_month: list[RetentionMonthDTO]
    registrations: int
