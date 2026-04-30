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

    country: str
    city: str
    percent: float


class AUDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    month_start: str
    value: int


class ActivityDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    avg_time_per_session: int = 0
    avg_session_per_day: int = 0

    dau_mau_ratio: float = 0.0
    mau_dau_ratio: float = 0.0

    total_users: int = 0
    activity_users: int = 0

    dau: list[AUDTO | None] = []
    mau: list[AUDTO | None] = []
    wau: list[AUDTO | None] = []
    user_locations: list[UserLocationDTO | None] = []
    user_devices: list[UserDeviceDTO | None] = []
    os_versions: list[OSversionDTO | None] = []
