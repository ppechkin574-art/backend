from content.dtos import (
    Locale,
    SubscriptionBenefitAdminDTO,
    SubscriptionBenefitCreateDTO,
    SubscriptionBenefitPublicDTO,
    SubscriptionBenefitUpdateDTO,
)
from content.repository import SubscriptionBenefitRepository


class SubscriptionBenefitService:
    """Wraps the repository with locale-resolution logic for the public
    endpoint and one-shot DTO mapping for the admin endpoint."""

    def __init__(self, repo: SubscriptionBenefitRepository):
        self.repo = repo

    # ─────── public ───────

    def list_active_localised(self, lang: Locale) -> list[SubscriptionBenefitPublicDTO]:
        rows = self.repo.list_active()
        return [self._to_public_dto(row, lang) for row in rows]

    @staticmethod
    def _to_public_dto(row, lang: Locale) -> SubscriptionBenefitPublicDTO:
        # KZ falls back to RU when the kz column is empty — we still
        # require non-empty kz at the DB layer, but be defensive in
        # case a future migration loosens that constraint.
        if lang == "kz":
            title = row.title_kz or row.title_ru
            description = row.description_kz or row.description_ru
        else:
            title = row.title_ru
            description = row.description_ru

        return SubscriptionBenefitPublicDTO(
            id=row.id,
            position=row.position,
            title=title,
            description=description,
        )

    # ─────── admin ───────

    def list_all_admin(self) -> list[SubscriptionBenefitAdminDTO]:
        return [SubscriptionBenefitAdminDTO.model_validate(r) for r in self.repo.list_all()]

    def get_admin(self, benefit_id: int) -> SubscriptionBenefitAdminDTO | None:
        row = self.repo.get(benefit_id)
        return SubscriptionBenefitAdminDTO.model_validate(row) if row else None

    def create(self, dto: SubscriptionBenefitCreateDTO) -> SubscriptionBenefitAdminDTO:
        row = self.repo.create(**dto.model_dump())
        return SubscriptionBenefitAdminDTO.model_validate(row)

    def update(
        self, benefit_id: int, dto: SubscriptionBenefitUpdateDTO
    ) -> SubscriptionBenefitAdminDTO | None:
        # exclude_unset → only patch fields the admin actually sent
        row = self.repo.update(benefit_id, **dto.model_dump(exclude_unset=True))
        return SubscriptionBenefitAdminDTO.model_validate(row) if row else None

    def delete(self, benefit_id: int) -> bool:
        return self.repo.delete(benefit_id)
