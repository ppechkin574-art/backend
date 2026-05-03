# import builtins
# from datetime import UTC, datetime, timedelta
# from uuid import UUID

# from sqlalchemy import func
# from sqlalchemy.orm import Session, joinedload

# from promocodes.models import PromoCode, PromoCodeUsage


# class PromocodeRepository:
#     def __init__(self, session: Session):
#         self._session = session

#     def create(
#         self,
#         code: str,
#         duration_days: int,
#         max_activations: int,
#         description: str | None,
#         expires_at: datetime | None,
#         created_by: UUID | None,
#     ) -> PromoCode:
#         promocode = PromoCode(
#             code=code,
#             duration_days=duration_days,
#             max_activations=max_activations,
#             description=description,
#             expires_at=expires_at,
#             created_by=created_by,
#         )
#         self._session.add(promocode)
#         self._session.flush()
#         self._session.refresh(promocode)
#         return promocode

#     def list(self) -> list[PromoCode]:
#         return (
#             self._session.query(PromoCode)
#             .options(joinedload(PromoCode.usages))
#             .order_by(PromoCode.created_at.desc())
#             .all()
#         )

#     def get_by_id(self, promocode_id: int) -> PromoCode | None:
#         return (
#             self._session.query(PromoCode)
#             .options(joinedload(PromoCode.usages))
#             .filter(PromoCode.id == promocode_id)
#             .first()
#         )

#     def get_by_code(self, code: str) -> PromoCode | None:
#         return (
#             self._session.query(PromoCode)
#             .options(joinedload(PromoCode.usages))
#             .filter(func.lower(PromoCode.code) == func.lower(code))
#             .first()
#         )

#     def increment_activation(self, promocode: PromoCode) -> None:
#         promocode.activations_count += 1
#         self._session.add(promocode)

#     def has_user_used(self, promocode_id: int, student_guid: UUID) -> bool:
#         return (
#             self._session.query(PromoCodeUsage)
#             .filter(
#                 PromoCodeUsage.promocode_id == promocode_id,
#                 PromoCodeUsage.student_guid == student_guid,
#             )
#             .first()
#             is not None
#         )

#     def add_usage(
#         self,
#         promocode_id: int,
#         student_guid: UUID,
#         duration_days: int,
#     ) -> PromoCodeUsage:
#         activated_at = datetime.now(UTC)
#         access_expires_at = activated_at + timedelta(days=duration_days)

#         usage = PromoCodeUsage(
#             promocode_id=promocode_id,
#             student_guid=student_guid,
#             activated_at=activated_at,
#             access_expires_at=access_expires_at,
#         )
#         self._session.add(usage)
#         self._session.flush()
#         self._session.refresh(usage)
#         return usage

#     def get_history(self, promocode_id: int) -> builtins.list[PromoCodeUsage]:
#         return (
#             self._session.query(PromoCodeUsage)
#             .filter(PromoCodeUsage.promocode_id == promocode_id)
#             .order_by(PromoCodeUsage.activated_at.desc())
#             .all()
#         )
