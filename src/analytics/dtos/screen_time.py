from datetime import date

from pydantic import BaseModel


class DailyScreenTimeDTO(BaseModel):
    date: date
    screen_time_seconds: int
    screen_time_formatted: str


class UserScreenTimeDTO(BaseModel):
    user_id: str
    period_start: date
    period_end: date
    total_screen_time_seconds: int
    average_daily_screen_time_seconds: int
    daily_screen_times: list[DailyScreenTimeDTO]


class ScreenTimeByActivityDTO(BaseModel):
    ent_subject: UserScreenTimeDTO
    ent_full: UserScreenTimeDTO
    trainer: UserScreenTimeDTO
    daily: UserScreenTimeDTO
    other: UserScreenTimeDTO
    total: UserScreenTimeDTO
