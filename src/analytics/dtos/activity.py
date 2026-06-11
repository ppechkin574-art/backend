from pydantic import BaseModel, ConfigDict


class UserDeviceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    device: str
    percent: float


class OSversionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    os: str
    percent: float


class UserLocationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    country: str | None = None
    city: str | None = None
    percent: float


class AUDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    month_start: str
    value: int


class ActivityDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    avg_time_per_session: float = 0
    avg_session_per_day: float = 0

    dau_mau_ratio: float = 0.0
    mau_dau_ratio: float = 0.0

    total_users: int = 0
    activity_users: int = 0
    # Distinct users whose FIRST `app_opened` event (MIN(event_time) per
    # user) landed within the last 7 days — a "new in the last week"
    # acquisition KPI computed on the event stream (the app never emits
    # `user_registered`, so first launch is the registration proxy; same
    # cohorting rule as get_retention()).
    new_users_7d: int = 0

    dau: list[AUDTO | None] = []
    mau: list[AUDTO | None] = []
    wau: list[AUDTO | None] = []
    user_locations: list[UserLocationDTO | None] = []
    user_devices: list[UserDeviceDTO | None] = []
    os_versions: list[OSversionDTO | None] = []
