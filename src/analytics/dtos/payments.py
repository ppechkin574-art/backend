from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PaymentMethodDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    percent: float


class PaymentLocationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    city: str
    amount: float
    payments: int


class PaymentInfoDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_payments: int
    total_amount: float
    unique_users: int
    avg_amount: float


class PaymentStatisticDTO(BaseModel):
    info: PaymentInfoDTO
    methods: list[PaymentMethodDTO]
    locations: list[PaymentLocationDTO]


class TopClientServiceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_fio: str
    user_id: UUID
    email: str | None
    total_amount: float
    total_payments: int
    last_payment_date: datetime | None


class TopClientRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    total_amount: float
    total_payments: int
    last_payment_date: datetime | None
    # Contact resolved from the `payments` table itself (pg_user_contact_email,
    # fallback pg_user_phone) — the paying users are deleted from Keycloak, so
    # we no longer resolve the user there.
    contact: str | None = None


class PaymentByMonthDTO(BaseModel):
    month: int
    total_amount: float
    total_payments: int


class PaymentsByYearDTO(BaseModel):
    year: int
    payments_by_month: list[PaymentByMonthDTO]


class LastPaymentServiceDTO(BaseModel):
    payment_id: int
    user_fio: str
    user_id: UUID
    email: str | None
    amount: float
    status: str
    method: str
    date: datetime
    month: int


class LastPaymentRepositoryDTO(BaseModel):
    payment_id: int
    user_id: UUID
    amount: float
    status: str
    method: str
    date: datetime
    month: int
