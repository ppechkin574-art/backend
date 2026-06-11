"""Wire shapes for the admin leaderboard hide-list endpoints.

- `LeaderboardHiddenListDTO` — read shape: the current hidden set.
  Returned by GET /admin/leaderboard/hidden AND by POST (so the admin
  panel can refresh its marked-rows set from one response).
- `LeaderboardHiddenUpdateDTO` — POST body: the user_ids to flip and
  whether to hide (true) or show (false) them.
"""

from pydantic import BaseModel, Field


class LeaderboardHiddenListDTO(BaseModel):
    user_ids: list[str]


class LeaderboardHiddenUpdateDTO(BaseModel):
    user_ids: list[str] = Field(default_factory=list)
    hidden: bool
