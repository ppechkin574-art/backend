"""Central service for policy-based leaderboard points calculation.

All point-awarding for leaderboard purposes flows through this module.
It reads the PointsPolicy table (admin-configured) to determine whether,
and how many, points to grant for a given activity completion.

ENT full/subject use their own atomic ``award_points_once()`` idempotency
guard and call ``calculate_amount()`` + ``passes_repeat_check()`` directly
so the atomic flag still protects against concurrent race conditions.

Trainer and daily_test (no atomic flag on their tables) use
``award_for_activity()`` which checks the audit log for idempotency.
"""

from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger(__name__)

# Maps policy activity_type → source_type stored in points_audit_log.
# "ent_full" keeps "ent_attempt" for backward compatibility with existing rows.
_AUDIT_SOURCE_TYPE: dict[str, str] = {
    "ent_full": "ent_attempt",
    "ent_subject": "ent_subject",
    "trainer": "trainer",
    "daily_test": "daily_test",
}


class PointsCalculatorService:
    """Stateless helper — instantiate where needed, pass UoW to each call."""

    def get_policy(self, activity_type: str, uow) -> object | None:
        return uow.points_policies.get_by_activity_type(activity_type)

    def calculate_amount(self, policy, score: int, total_questions: int) -> int:
        """Return points to award based on policy settings.

        Returns 0 if min_score_percent threshold not met or mode/values
        would produce a non-positive amount.
        """
        if total_questions > 0 and policy.min_score_percent > 0:
            pct = score / total_questions * 100
            if pct < policy.min_score_percent:
                return 0

        if policy.mode == "fixed":
            return max(0, policy.fixed_points or 0)

        # score_based: points = correct_answers * multiplier
        multiplier = policy.score_multiplier if policy.score_multiplier is not None else 1.0
        return max(0, int(score * multiplier))

    def passes_repeat_check(
        self,
        policy,
        user_id: UUID,
        calculated_points: int,
        uow,
    ) -> bool:
        """Return True if repeat_mode allows awarding points to this user."""
        if policy.repeat_mode == "always":
            return True

        from security.models import PointsAuditLog

        source_type = _AUDIT_SOURCE_TYPE.get(policy.activity_type, policy.activity_type)

        if policy.repeat_mode == "first_only":
            exists = (
                uow.session.query(PointsAuditLog.id)
                .filter(
                    PointsAuditLog.user_id == user_id,
                    PointsAuditLog.source_type == source_type,
                    PointsAuditLog.points_delta > 0,
                )
                .first()
            )
            return exists is None

        if policy.repeat_mode == "improvement_only":
            row = (
                uow.session.query(PointsAuditLog.points_delta)
                .filter(
                    PointsAuditLog.user_id == user_id,
                    PointsAuditLog.source_type == source_type,
                    PointsAuditLog.points_delta > 0,
                )
                .order_by(PointsAuditLog.points_delta.desc())
                .first()
            )
            prev_best = row[0] if row else 0
            return calculated_points > prev_best

        return True

    def award_for_activity(
        self,
        uow,
        user_id: UUID,
        activity_type: str,
        score: int,
        total_questions: int,
        source_id: str,
    ) -> int:
        """Award points for trainer / daily_test with audit-log idempotency.

        Returns the number of points actually awarded (0 if nothing awarded).
        Must be called within an active UoW context (session open).
        """
        policy = uow.points_policies.get_by_activity_type(activity_type)
        if not policy or not policy.is_enabled:
            return 0

        source_type = _AUDIT_SOURCE_TYPE.get(activity_type, activity_type)

        # Idempotency: check audit log for this specific session
        from security.models import PointsAuditLog

        already = (
            uow.session.query(PointsAuditLog.id)
            .filter(
                PointsAuditLog.user_id == user_id,
                PointsAuditLog.source_type == source_type,
                PointsAuditLog.source_id == source_id,
            )
            .first()
        )
        if already is not None:
            return 0

        points = self.calculate_amount(policy, score, total_questions)
        if points <= 0:
            return 0

        if not self.passes_repeat_check(policy, user_id, points, uow):
            return 0

        uow.user_points.add_points(
            user_id,
            points,
            source_type=source_type,
            source_id=source_id,
        )
        logger.info(
            "Awarded %s points to user %s for %s (source_id=%s)",
            points,
            user_id,
            activity_type,
            source_id,
        )
        return points
