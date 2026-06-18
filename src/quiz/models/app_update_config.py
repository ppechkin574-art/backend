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
from sqlalchemy.dialects.postgresql import JSONB
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

    # Highest build that is ACTUALLY live in each platform's store
    # (operator-maintained). Guards against forcing users onto a version
    # that is not yet published: the admin PUT rejects min_build >
    # last_known_build. 0 = unknown (no guard, the panel warns instead).
    ios_last_known_build = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    android_last_known_build = Column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Soft-update tier: when min_build <= running build < recommended_build
    # the app shows a DISMISSIBLE "update available" prompt (once/day)
    # instead of the blocking gate. 0 = no soft prompt.
    ios_recommended_build = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    android_recommended_build = Column(
        Integer, nullable=False, default=0, server_default="0"
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


class AppUpdateConfigAuditLog(Base):
    """Append-only audit trail for every change to the force-update config.

    One row per successful admin save: a JSONB snapshot of all config
    fields BEFORE and AFTER the change, plus who/when. Powers the history
    view and one-click rollback in the admin panel (rollback just reloads
    an older `after_values` snapshot into the form and re-saves through the
    same validated PUT). Never updated or deleted — pure forensics.
    """

    __tablename__ = "app_update_config_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    changed_at = Column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    changed_by = Column(String, nullable=True)
    before_values = Column(JSONB, nullable=False, default=dict)
    after_values = Column(JSONB, nullable=False, default=dict)

    def __repr__(self) -> str:
        return f"<AppUpdateConfigAuditLog id={self.id} by={self.changed_by}>"
