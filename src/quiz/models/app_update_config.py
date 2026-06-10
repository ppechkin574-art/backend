"""Admin-controlled force-update config for the mobile app.

Single-row (singleton) table: `id` is ALWAYS 1. Replaces the previous
env-var driven `/app/update-config` so the operator can flip the
minimum-required build / store URL per platform from the admin panel
WITHOUT a backend redeploy.

The public endpoint `GET /app/update-config` reads this row and compares
the app's own build number against `min_build` for its platform. Default
`min_build = 0` → the app never force-updates (its build is always >= 0).

Additive only: no FK into/out of this table, no relationships, no
builtin-shadowing column/method names (deliberately avoids `list`,
`type`, etc. — a recent deploy crashed at import time on exactly that).
"""

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from database import Base


class AppUpdateConfig(Base):
    __tablename__ = "app_update_config"

    # Singleton: there is exactly one row and its id is always 1.
    id = Column(Integer, primary_key=True)

    ios_min_build = Column(Integer, nullable=False, default=0, server_default="0")
    android_min_build = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    ios_store_url = Column(String, nullable=False, default="", server_default="")
    android_store_url = Column(
        String, nullable=False, default="", server_default=""
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )
    updated_by = Column(String, nullable=True)

    def __repr__(self) -> str:
        return (
            "<AppUpdateConfig "
            f"ios={self.ios_min_build} android={self.android_min_build}>"
        )
