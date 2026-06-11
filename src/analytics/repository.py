from datetime import date, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import case, cast, desc, exists, func, not_, select, text
from sqlalchemy.dialects.postgresql import UUID as UUIDType
from sqlalchemy.orm import Session, aliased
from sqlalchemy.types import TIMESTAMP, Integer, Numeric, String

from analytics.dtos.activity import (
    AUDTO,
    ActivityDTO,
    OSversionDTO,
    UserDeviceDTO,
    UserLocationDTO,
)
from analytics.dtos.api_filters import PeriodEnum
from analytics.dtos.api_timing import ApiTimingRowDTO
from analytics.dtos.payments_by_gateway import PaymentByGatewayRowDTO
from analytics.dtos.efficienty import (
    EfficientyDTO,
    EntEfficientyDTO,
    HardTopicDTO,
    PopularEntityDTO,
    ProgressEfficientyDTO,
    TrainerEfficientyDTO,
)
from analytics.dtos.enums import MistakeCategory, UserActivityEnum
from analytics.dtos.events import EventCreateRepositoryDTO
from analytics.dtos.payments import (
    LastPaymentRepositoryDTO,
    PaymentByMonthDTO,
    PaymentInfoDTO,
    PaymentLocationDTO,
    PaymentMethodDTO,
    PaymentsByYearDTO,
    PaymentStatisticDTO,
    TopClientRepositoryDTO,
)
from analytics.dtos.retention import RetentionDTO, RetentionMonthDTO
from analytics.dtos.screen_time import (
    DailyScreenTimeDTO,
    ScreenTimeByActivityDTO,
    UserScreenTimeDTO,
)
from analytics.models import UserActivity
from payments.dtos import PaymentStatus
from payments.models import Payment
from quiz.models.edu_content import Subject, Topic
from quiz.models.ent import EntOption
from quiz.models.trainer import Trainer


class AnalyticRepositoryInterface(Protocol):
    def save_event(self, event_dto: EventCreateRepositoryDTO) -> None:
        raise NotImplementedError

    def get_activity(self) -> ActivityDTO:
        raise NotImplementedError

    def get_efficienty(self) -> EfficientyDTO:
        raise NotImplementedError

    def get_retention(self) -> RetentionDTO:
        raise NotImplementedError

    def get_payment_statistic(
        self,
        status: PaymentStatus | None,
        period: PeriodEnum | None,
        date_from: date | None,
        date_to: date | None,
    ) -> PaymentStatisticDTO:
        raise NotImplementedError

    def get_payments_top_clients(self, show_all: bool) -> list[TopClientRepositoryDTO]:
        raise NotImplementedError

    def get_payments_by_year(self) -> list[PaymentsByYearDTO]:
        raise NotImplementedError

    def get_payments_last(
        self, page: int, status: PaymentStatus | None, search: str | None
    ) -> list[LastPaymentRepositoryDTO]:
        raise NotImplementedError

    def get_api_timing_summary(
        self, hours: int, platform: str | None, app_version: str | None
    ) -> list[ApiTimingRowDTO]:
        raise NotImplementedError

    def get_payments_by_gateway(self, hours: int) -> list[PaymentByGatewayRowDTO]:
        raise NotImplementedError


class AnalyticRepository:
    def __init__(self, session: Session, max_session_hours: int = 8):
        self._session = session
        self.MAX_SESSION_HOURS = max_session_hours

    def save_event(self, event_dto: EventCreateRepositoryDTO) -> None:
        user_activity = UserActivity(**event_dto.model_dump())
        self._session.add(user_activity)
        self._session.flush()

    def get_activity(self) -> ActivityDTO:
        # DAU averaged over days: count distinct users per calendar day in a
        # FROM-clause subquery, then avg the per-day counts. (Using the grouped
        # count as a scalar subquery raises CardinalityViolation, because the
        # GROUP BY makes it return one row per day instead of a single value.)
        dau_per_day = (
            select(func.count(func.distinct(UserActivity.user_id)).label("cnt"))
            .group_by(func.date(UserActivity.event_time))
            .subquery()
        )
        avg_dau_query = select(func.avg(dau_per_day.c.cnt))

        avg_dau = self._session.execute(avg_dau_query).scalar()

        # MAU averaged over months: same pattern, grouped by month.
        mau_per_month = (
            select(func.count(func.distinct(UserActivity.user_id)).label("cnt"))
            .group_by(func.date_trunc("month", UserActivity.event_time))
            .subquery()
        )
        avg_mau_query = select(func.avg(mau_per_month.c.cnt))

        avg_mau = self._session.execute(avg_mau_query).scalar()
        total_users = self._session.execute(select(func.count(func.distinct(UserActivity.user_id)))).scalar() or 0
        # New-in-last-7-days: cohort each user on their FIRST `app_opened`
        # (MIN(event_time) per user — the same first-use / registration
        # proxy get_retention uses, since the app never emits
        # `user_registered`), then count those whose first launch falls
        # inside the trailing 7-day window.
        first_seen_7d = (
            select(
                UserActivity.user_id,
                func.min(UserActivity.event_time).label("first_event_time"),
            )
            .where(
                UserActivity.event_name == UserActivityEnum.app_opened.value,
                UserActivity.user_id.isnot(None),
            )
            .group_by(UserActivity.user_id)
            .subquery()
        )
        new_users_7d = (
            self._session.execute(
                select(func.count()).where(
                    first_seen_7d.c.first_event_time >= func.now() - text("interval '7 days'")
                )
            ).scalar()
            or 0
        )
        active_users = (
            self._session.execute(
                select(func.count(func.distinct(UserActivity.user_id))).where(
                    UserActivity.event_time >= func.now() - text("interval '30 days'")
                )
            ).scalar()
            or 0
        )
        sessions = (
            select(
                UserActivity.user_id,
                UserActivity.session_id,
                (
                    func.extract(
                        "epoch",
                        func.max(UserActivity.event_time) - func.min(UserActivity.event_time),
                    )
                ).label("session_length_sec"),
                func.date(UserActivity.event_time).label("day"),
            )
            .group_by(
                UserActivity.user_id,
                UserActivity.session_id,
                func.date(UserActivity.event_time),
            )
            .subquery()
        )
        # Average session length over all (user, session, day) rows.
        # session_length_sec is double precision (extract(epoch ...)); cast the
        # average to numeric so round(value, n) resolves (Postgres has no
        # round(double precision, int)).
        avg_session_time = self._session.execute(
            select(func.round(cast(func.avg(sessions.c.session_length_sec), Numeric), 0))
        ).scalar()

        # Average number of sessions a user opens per active day: count
        # sessions per (user, day) in a FROM-clause subquery, then avg those
        # counts. (Previously a grouped scalar subquery -> CardinalityViolation.)
        sessions_per_user_day = (
            select(func.count(sessions.c.session_id).label("sessions_count"))
            .group_by(sessions.c.user_id, sessions.c.day)
            .subquery()
        )
        avg_sessions_per_day = self._session.execute(
            select(func.round(func.avg(sessions_per_user_day.c.sessions_count), 2))
        ).scalar()

        activity_dto = ActivityDTO(
            avg_session_per_day=avg_sessions_per_day if avg_sessions_per_day else 0,
            avg_time_per_session=avg_session_time if avg_session_time else 0,
            total_users=total_users,
            activity_users=active_users,
            new_users_7d=new_users_7d,
            dau_mau_ratio=avg_dau / avg_mau if avg_mau else 0,
            mau_dau_ratio=avg_mau / avg_dau if avg_dau else 0,
        )
        activity_dto.dau = self._get_dau()
        activity_dto.mau = self._get_mau()
        activity_dto.wau = self._get_wau()
        activity_dto.user_locations = self._get_locations()
        activity_dto.user_devices = self._get_user_devices()
        activity_dto.os_versions = self._get_os_versions()
        return activity_dto

    def get_efficienty(self) -> EfficientyDTO:
        ent_stat = self._get_ent_statistic()
        trainer_stat = self._get_trainer_statistic()
        progress_stat = self._get_progress()
        return EfficientyDTO(ent=ent_stat, trainer=trainer_stat, progress=progress_stat)

    def get_retention(self) -> RetentionDTO:
        # The app never emits `user_registered`, so cohort on each user's FIRST
        # `app_opened` (it fires on every launch) as a first-use / registration
        # proxy. first_seen has exactly one row per user_id (MIN over their
        # app_opened events); the return-window LEFT JOIN tests whether the user
        # opened the app again in the day+1 / week+1 / month+1 window after that
        # first launch. Ratios are emitted on a 0..1 scale (the dashboard
        # multiplies by 100 itself).
        first_seen = (
            select(
                UserActivity.user_id,
                func.date_trunc("month", func.min(UserActivity.event_time)).label("install_month"),
                func.min(UserActivity.event_time).label("first_event_date"),
            )
            .where(
                UserActivity.event_name == UserActivityEnum.app_opened.value,
                UserActivity.user_id.isnot(None),
            )
            .group_by(UserActivity.user_id)
            .subquery()
        )
        retention_q = (
            select(
                first_seen.c.install_month,
                func.count(func.distinct(first_seen.c.user_id)).label("new_users"),
                # D1 — returned on/after the day following first launch
                func.count(
                    func.distinct(
                        case(
                            (
                                UserActivity.event_time >= first_seen.c.first_event_date + text("interval '1 day'"),
                                first_seen.c.user_id,
                            ),
                        )
                    )
                ).label("d1"),
                # W1 — returned within a week after first launch
                func.count(
                    func.distinct(
                        case(
                            (
                                (UserActivity.event_time <= first_seen.c.first_event_date + text("interval '7 day'"))
                                & (UserActivity.event_time > first_seen.c.first_event_date),
                                first_seen.c.user_id,
                            ),
                        )
                    )
                ).label("w1"),
                # M1 — returned within a month after first launch
                func.count(
                    func.distinct(
                        case(
                            (
                                (UserActivity.event_time <= first_seen.c.first_event_date + text("interval '30 day'"))
                                & (UserActivity.event_time > first_seen.c.first_event_date),
                                first_seen.c.user_id,
                            ),
                        )
                    )
                ).label("m1"),
            )
            .join(
                UserActivity,
                (UserActivity.user_id == first_seen.c.user_id)
                & (UserActivity.event_name == UserActivityEnum.app_opened.value),
                isouter=True,
            )
            .group_by(first_seen.c.install_month)
            .order_by(first_seen.c.install_month)
        )
        result = self._session.execute(retention_q).mappings().all()
        retention_by_month = []
        total_d1_count = 0
        total_w1_count = 0
        total_m1_count = 0
        total_regs = 0
        for r in result:
            total = r["new_users"]
            total_regs += total
            total_d1_count += r["d1"]
            total_w1_count += r["w1"]
            total_m1_count += r["m1"]
            retention_by_month.append(
                RetentionMonthDTO(
                    month_start=r["install_month"].strftime("%Y-%m"),
                    registrations=total,
                    d1=round(r["d1"] / total, 4) if total else 0,
                    w1=round(r["w1"] / total, 4) if total else 0,
                    m1=round(r["m1"] / total, 4) if total else 0,
                )
            )
        return RetentionDTO(
            d1=round(total_d1_count / total_regs, 4) if total_regs else 0,
            w1=round(total_w1_count / total_regs, 4) if total_regs else 0,
            m1=round(total_m1_count / total_regs, 4) if total_regs else 0,
            registrations=total_regs,
            retention_rate_by_month=retention_by_month,
        )

    def get_payment_statistic(
        self,
        status: PaymentStatus | None,
        period: PeriodEnum | None,
        date_from: date | None,
        date_to: date | None,
    ) -> PaymentStatisticDTO:
        info = self._get_payments_info(status, period, date_from, date_to)
        methods = self._get_payment_methods(status, period, date_from, date_to)
        locations = self._get_payment_locations(status, period, date_from, date_to)
        return PaymentStatisticDTO(info=info, methods=methods, locations=locations)

    def _get_payments_table_filters(
        self,
        status: PaymentStatus | None,
        period: PeriodEnum | None,
        date_from: date | None,
        date_to: date | None,
    ):
        """Filters for the real `payments` table.

        Revenue analytics read from `payments` (the FreedomPay / IAP write
        path), not from `user_activity` events — the app never emits
        `purchase_*` events, so the old event-stream queries always returned 0.
        Defaults to status='paid' (real revenue), matching the previous
        "purchase_success" default.
        """
        filters = [Payment.status == (status.value if status else PaymentStatus.PAID.value)]
        if date_from:
            filters.append(Payment.created_at >= date_from)
        if date_to:
            filters.append(Payment.created_at <= date_to)
        if period and not date_from and not date_to:
            match period:
                case PeriodEnum.today:
                    condition = datetime.combine(date.today(), datetime.min.time())
                case PeriodEnum.week:
                    condition = date.today() - timedelta(days=7)
                case PeriodEnum.month:
                    condition = date.today() - timedelta(days=30)
                case PeriodEnum.quarter:
                    condition = date.today() - timedelta(days=90)
                case PeriodEnum.year:
                    condition = date.today() - timedelta(days=365)
            filters.append(Payment.created_at >= condition)
        return filters

    def _get_payments_info(
        self,
        status: PaymentStatus | None,
        period: PeriodEnum | None,
        date_from: date | None,
        date_to: date | None,
    ) -> PaymentStatisticDTO:
        filters = self._get_payments_table_filters(status, period, date_from, date_to)
        q = select(
            func.coalesce(func.count(), 0).label("total_payments"),
            func.coalesce(func.sum(Payment.amount), 0.0).label("total_amount"),
            func.coalesce(func.avg(Payment.amount), 0.0).label("avg_amount"),
            func.coalesce(func.count(func.distinct(Payment.user_id)), 0).label("unique_users"),
        ).where(*filters)
        result = self._session.execute(q).first()
        return PaymentInfoDTO.model_validate(result._mapping)

    def get_payments_top_clients(self, show_all: bool) -> list[TopClientRepositoryDTO]:
        # Top spenders from the real `payments` table (status='paid'), not the
        # event stream. user_id is a Keycloak sub (UUID string); skip NULLs.
        # The contact (email, fallback phone) is taken from one of this user's
        # paid payment rows — most recent with a non-null contact — instead of
        # resolving the (now-deleted) Keycloak user.
        contact_inner = aliased(Payment)
        contact_subq = (
            select(
                func.coalesce(
                    contact_inner.pg_user_contact_email,
                    contact_inner.pg_user_phone,
                )
            )
            .where(
                contact_inner.user_id == Payment.user_id,
                contact_inner.status == PaymentStatus.PAID.value,
                func.coalesce(
                    contact_inner.pg_user_contact_email,
                    contact_inner.pg_user_phone,
                ).isnot(None),
            )
            .order_by(desc(contact_inner.created_at))
            .limit(1)
            .scalar_subquery()
        )
        q = (
            select(
                cast(Payment.user_id, UUIDType).label("user_id"),
                func.coalesce(func.sum(Payment.amount), 0.0).label("total_amount"),
                func.count().label("total_payments"),
                func.max(Payment.created_at).label("last_payment_date"),
                contact_subq.label("contact"),
            )
            .where(
                Payment.status == PaymentStatus.PAID.value,
                Payment.user_id.isnot(None),
            )
            .group_by(Payment.user_id)
            .order_by(desc("total_amount"))
        )
        if not show_all:
            q = q.limit(3)
        result = self._session.execute(q).all()
        return [TopClientRepositoryDTO.model_validate(r._mapping) for r in result]

    def get_payments_by_year(self) -> list[LastPaymentRepositoryDTO]:
        q = (
            select(
                func.extract("year", UserActivity.event_time).label("year"),
                func.extract("month", UserActivity.event_time).label("month"),
                func.coalesce(func.sum(UserActivity.meta["amount"].as_float()), 0.0).label("total_amount"),
                func.count().label("total_payments"),
            )
            .where(UserActivity.event_name == UserActivityEnum.purchase_success.value)
            .group_by(
                func.extract("year", UserActivity.event_time),
                func.extract("month", UserActivity.event_time),
            )
            .order_by(desc("year"), desc("month"))
        )
        result = self._session.execute(q).all()
        payments_by_year = {}
        for r in result:
            year = int(r.year)
            month_data = PaymentByMonthDTO(
                month=int(r.month),
                total_amount=r.total_amount,
                total_payments=r.total_payments,
            )
            if year not in payments_by_year:
                payments_by_year[year] = []
            payments_by_year[year].append(month_data)
        return [PaymentsByYearDTO(year=year, payments_by_month=months) for year, months in payments_by_year.items()]

    def get_payments_last(
        self, page: int, status: PaymentStatus | None, search: str | None
    ) -> list[LastPaymentRepositoryDTO]:
        page_size = 10
        q = select(
            UserActivity.meta["payment_id"].as_integer().label("payment_id"),
            UserActivity.user_id,
            UserActivity.meta["amount"].as_float().label("amount"),
            case(
                (
                    UserActivity.event_name == UserActivityEnum.purchase_success.value,
                    PaymentStatus.PAID.value,
                ),
                (
                    UserActivity.event_name == UserActivityEnum.purchase_failed.value,
                    PaymentStatus.FAILED.value,
                ),
                (
                    UserActivity.event_name == UserActivityEnum.purchase_initiated.value,
                    PaymentStatus.PENDING.value,
                ),
            ).label("status"),
            UserActivity.meta["method"].as_string().label("method"),
            UserActivity.event_time.label("date"),
            func.extract("month", UserActivity.event_time).label("month"),
            UserActivity.meta["promo"].as_string().label("promo"),
        ).where(
            UserActivity.event_name.in_(
                [
                    UserActivityEnum.purchase_success.value,
                    UserActivityEnum.purchase_failed.value,
                    UserActivityEnum.purchase_initiated.value,
                ]
            )
        )
        if status:
            match status:
                case PaymentStatus.PAID:
                    q = q.where(UserActivity.event_name == UserActivityEnum.purchase_success.value)
                case PaymentStatus.FAILED:
                    q = q.where(UserActivity.event_name == UserActivityEnum.purchase_failed.value)
                case PaymentStatus.PENDING:
                    subq = select(UserActivity.id).where(
                        UserActivity.user_id == UserActivity.user_id,
                        UserActivity.session_id == UserActivity.session_id,
                        UserActivity.event_name.in_(
                            [
                                UserActivityEnum.purchase_success.value,
                                UserActivityEnum.purchase_failed.value,
                            ]
                        ),
                    )
                    q = q.where(
                        (UserActivity.event_name == UserActivityEnum.purchase_initiated.value) & not_(exists(subq))
                    )
        if search:
            ...
        q = q.distinct(UserActivity.meta["payment_id"].as_integer())
        q = (
            q.order_by(
                UserActivity.meta["payment_id"].as_integer(),
                desc(UserActivity.event_time),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = self._session.execute(q).all()
        return [LastPaymentRepositoryDTO.model_validate(r._mapping) for r in result]

    def _get_payment_locations(
        self,
        status: PaymentStatus | None,
        period: PeriodEnum | None,
        date_from: date | None,
        date_to: date | None,
    ) -> PaymentLocationDTO:
        UserActivityOuter = aliased(UserActivity)
        filters = self._get_payment_filters(UserActivityOuter, status, period, date_from, date_to)
        q = (
            select(
                func.coalesce(func.count(), 0).label("payments"),
                func.coalesce(func.sum(UserActivityOuter.meta["amount"].as_float()), 0.0).label("amount"),
                UserActivityOuter.city,
            )
            .where(*filters)
            .group_by(UserActivityOuter.city)
        )
        result = self._session.execute(q).all()
        return [PaymentLocationDTO.model_validate(r._mapping) for r in result]

    def _get_payment_methods(
        self,
        status: PaymentStatus | None,
        period: PeriodEnum | None,
        date_from: date | None,
        date_to: date | None,
    ) -> PaymentMethodDTO:
        # Payment-method breakdown from the real `payments` table
        # (pg_payment_method, e.g. google_play / card / freedompay).
        filters = self._get_payments_table_filters(status, period, date_from, date_to)
        method_name = func.coalesce(Payment.pg_payment_method, "freedompay")
        total_q = select(func.count()).where(*filters).scalar_subquery()
        q = (
            select(
                func.coalesce(func.count() * 100.0 / total_q, 0.0).label("percent"),
                method_name.label("name"),
            )
            .where(*filters)
            .group_by(method_name)
        )
        result = self._session.execute(q).all()
        return [PaymentMethodDTO.model_validate(r._mapping) for r in result]

    def _get_payment_filters(
        self,
        alias,
        status: PaymentStatus | None,
        period: PeriodEnum | None,
        date_from: date | None,
        date_to: date | None,
    ):
        event = UserActivityEnum.purchase_success.value
        filters = []
        if status:
            if status == PaymentStatus.FAILED:
                event = UserActivityEnum.purchase_failed.value
            elif status == PaymentStatus.PENDING:
                event = UserActivityEnum.purchase_initiated.value
                subq = select(UserActivity.id).where(
                    UserActivity.user_id == alias.user_id,
                    UserActivity.session_id == alias.session_id,
                    UserActivity.event_name.in_(
                        [
                            UserActivityEnum.purchase_success.value,
                            UserActivityEnum.purchase_failed.value,
                        ]
                    ),
                )
                filters.append(not_(exists(subq)))
        filters.append(alias.event_name == event)
        if date_from:
            filters.append(alias.event_time >= date_from)
        if date_to:
            filters.append(alias.event_time <= date_to)
        if period and not date_from and not date_to:
            match period:
                case PeriodEnum.today:
                    condition = datetime.combine(date.today(), datetime.min.time())
                case PeriodEnum.week:
                    condition = date.today() - timedelta(days=7)
                case PeriodEnum.month:
                    condition = date.today() - timedelta(days=30)
                case PeriodEnum.quarter:
                    condition = date.today() - timedelta(days=90)
                case PeriodEnum.year:
                    condition = date.today() - timedelta(days=365)
            filters.append(alias.event_time >= condition)
        return filters

    def _get_ent_statistic(self):
        q = select(
            func.coalesce(func.count(UserActivity.id), 0).label("total_attempts"),
            func.coalesce(func.avg(UserActivity.meta["score"].as_float()), 0.0).label("avg_score"),
            func.coalesce(func.avg(UserActivity.meta["spend_time"].as_integer()), 0.0).label("avg_time"),
        ).where(UserActivity.event_name == UserActivityEnum.ent_subject_completed.value)
        result = self._session.execute(q).first()
        popular_subjects_query = (
            select(
                func.count(UserActivity.id).label("attempts"),
                Subject.name.label("name"),
            )
            .join(
                EntOption,
                EntOption.id == UserActivity.meta["ent_option_id"].as_integer(),
            )
            .join(Subject, Subject.id == EntOption.subject_id)
            .where(UserActivity.event_name == UserActivityEnum.trainer_answer.value)
            .group_by(Subject.name)
            .order_by(desc(func.count(UserActivity.id)))
            .limit(5)
        )
        popular_subjects = self._session.execute(popular_subjects_query).all()
        return EntEfficientyDTO(
            **result._mapping,
            popular_subjects=[PopularEntityDTO.model_validate(r._mapping) for r in popular_subjects],
        )

    def _get_trainer_statistic(self):
        q = select(
            func.coalesce(func.count(UserActivity.id), 0).label("total_attempts"),
            func.coalesce(func.avg(UserActivity.meta["score"].as_float()), 0.0).label("avg_score"),
            func.coalesce(func.avg(UserActivity.meta["spend_time"].as_integer()), 0.0).label("avg_anwer_time"),
        ).where(UserActivity.event_name == UserActivityEnum.trainer_answer.value)
        result = self._session.execute(q).first()
        popular_topics_query = (
            select(
                func.count(UserActivity.id).label("attempts"),
                Topic.name.label("name"),
            )
            .join(Trainer, Trainer.id == UserActivity.meta["trainer_id"].as_integer())
            .join(Topic, Topic.id == Trainer.topic_id)
            .where(UserActivity.event_name == UserActivityEnum.trainer_answer.value)
            .group_by(Topic.name)
            .order_by(desc(func.count(UserActivity.id)))
            .limit(5)
        )
        mistake_percent = (
            (func.sum(case((UserActivity.meta["score"].as_float() > 0.0, 0), else_=1)) / func.count() * 100.0)
            .cast(Integer)
            .label("mistake_percent")
        )
        hard_topics_q = (
            select(
                Topic.name.label("name"),
                mistake_percent,
                case(
                    (mistake_percent < 30, MistakeCategory.low.value),
                    else_=case(
                        (mistake_percent < 60, MistakeCategory.medium.value),
                        else_=MistakeCategory.hard.value,
                    ),
                ).label("mistake_category"),
            )
            .join(Trainer, Trainer.id == UserActivity.meta["trainer_id"].as_integer())
            .join(Topic, Topic.id == Trainer.topic_id)
            .where(UserActivity.event_name == UserActivityEnum.trainer_answer.value)
            .group_by(Topic.name)
            .order_by(desc(mistake_percent))
            .limit(5)
        )

        popular_subjects = self._session.execute(popular_topics_query).all()
        hard_topics = self._session.execute(hard_topics_q).all()
        return TrainerEfficientyDTO(
            **result._mapping,
            popular_topics=[PopularEntityDTO.model_validate(r._mapping) for r in popular_subjects],
            hard_topics=[HardTopicDTO.model_validate(r._mapping) for r in hard_topics],
        )

    def _get_progress(self):
        completed_trainers = self._session.execute(
            select(func.count(UserActivity.id)).where(
                UserActivity.event_name == UserActivityEnum.trainer_completed.value
            )
        ).scalar_one_or_none()
        if not completed_trainers:
            completed_trainers = 0
        total_trainers = self._session.query(Trainer).count()

        return ProgressEfficientyDTO(
            total_topics=total_trainers,
            completed_topics=completed_trainers,
            avg_progress_percent=(completed_trainers / total_trainers * 100 if total_trainers else 0),
        )

    def _get_dau(self):
        dau_per_day = (
            select(
                func.date(UserActivity.event_time).label("day"),
                func.count(
                    func.distinct(
                        func.coalesce(
                            func.cast(UserActivity.user_id, String),
                            UserActivity.device_id,
                        )
                    )
                ).label("dau"),
            ).group_by(func.date(UserActivity.event_time))
        ).subquery()
        avg_dau_q = (
            select(
                cast(func.date_trunc("month", dau_per_day.c.day), String).label("month_start"),
                func.round(func.avg(dau_per_day.c.dau), 0).label("value"),
            )
            .group_by(func.date_trunc("month", dau_per_day.c.day))
            .order_by(func.date_trunc("month", dau_per_day.c.day))
        )
        daus = self._session.execute(avg_dau_q).all()
        return [AUDTO.model_validate(dau) for dau in daus]

    def _get_mau(self):
        q = (
            select(
                func.date_trunc("month", UserActivity.event_time).cast(String).label("month_start"),
                func.count(
                    func.distinct(
                        func.coalesce(
                            func.cast(UserActivity.user_id, String),
                            UserActivity.device_id,
                        )
                    )
                ).label("value"),
            )
            .group_by(func.date_trunc("month", UserActivity.event_time))
            .order_by(func.date_trunc("month", UserActivity.event_time))
        )
        maus = self._session.execute(q).all()
        return [AUDTO.model_validate(mau) for mau in maus]

    def _get_wau(self):
        wau_per_week = select(
            func.date_trunc("week", UserActivity.event_time).cast(TIMESTAMP).label("week_start"),
            func.count(
                func.distinct(func.coalesce(func.cast(UserActivity.user_id, String), UserActivity.device_id))
            ).label("wau"),
        ).group_by(func.date_trunc("week", UserActivity.event_time))
        avg_wau_query = (
            select(
                cast(func.date_trunc("month", wau_per_week.c.week_start), String).label("month_start"),
                func.round(func.avg(wau_per_week.c.wau), 0).label("value"),
            )
            .group_by(func.date_trunc("month", wau_per_week.c.week_start))
            .order_by(func.date_trunc("month", wau_per_week.c.week_start))
        )
        waus = self._session.execute(avg_wau_query).all()
        return [AUDTO.model_validate(wau) for wau in waus]

    def _get_user_devices(self):
        q = (
            select(
                UserActivity.platform.label("device"),
                (
                    func.count(
                        func.distinct(
                            func.coalesce(
                                func.cast(UserActivity.user_id, String),
                                UserActivity.device_id,
                            )
                        )
                    )
                    * 100.0
                    / func.sum(
                        func.count(
                            func.distinct(
                                func.coalesce(
                                    func.cast(UserActivity.user_id, String),
                                    UserActivity.device_id,
                                )
                            )
                        )
                    ).over()
                ).label("percent"),
            )
            .group_by(UserActivity.platform)
            .order_by(func.count().desc())
        )
        devices = self._session.execute(q).all()
        return [UserDeviceDTO.model_validate(device) for device in devices]

    def _get_os_versions(self):
        q = (
            select(
                UserActivity.os_version.label("os"),
                (
                    func.count(
                        func.distinct(
                            func.coalesce(
                                func.cast(UserActivity.user_id, String),
                                UserActivity.device_id,
                            )
                        )
                    )
                    * 100.0
                    / func.sum(
                        func.count(
                            func.distinct(
                                func.coalesce(
                                    func.cast(UserActivity.user_id, String),
                                    UserActivity.device_id,
                                )
                            )
                        )
                    ).over()
                ).label("percent"),
            )
            .group_by(UserActivity.os_version)
            .order_by(func.count().desc())
        )
        os_versions = self._session.execute(q).all()
        return [OSversionDTO.model_validate(os) for os in os_versions]

    def _get_locations(self):
        q = (
            select(
                UserActivity.country,
                UserActivity.city,
                (
                    func.count(
                        func.distinct(
                            func.coalesce(
                                func.cast(UserActivity.user_id, String),
                                UserActivity.device_id,
                            )
                        )
                    )
                    * 100.0
                    / func.sum(
                        func.count(
                            func.distinct(
                                func.coalesce(
                                    func.cast(UserActivity.user_id, String),
                                    UserActivity.device_id,
                                )
                            )
                        )
                    ).over()
                ).label("percent"),
            )
            .group_by(UserActivity.country, UserActivity.city)
            .order_by(func.count().desc())
        )
        locations = self._session.execute(q).all()
        return [UserLocationDTO.model_validate(location) for location in locations]

    def get_user_screen_time(self, user_id: UUID, start_date: date, end_date: date) -> UserScreenTimeDTO:
        events_query = (
            select(
                UserActivity.event_name,
                UserActivity.event_time,
            )
            .where(
                UserActivity.user_id == user_id,
                UserActivity.event_time >= start_date,
                UserActivity.event_time < end_date + timedelta(days=1),
            )
            .order_by(UserActivity.event_time)
        )

        events = self._session.execute(events_query).all()

        if not events:
            return self._get_empty_screen_time(user_id, start_date, end_date)

        sessions = []
        current_session = []
        SESSION_TIMEOUT_MINUTES = 240

        for i, event in enumerate(events):
            event_time = event.event_time

            if not current_session:
                current_session.append(event)
            else:
                prev_event_time = events[i - 1].event_time
                time_diff = (event_time - prev_event_time).total_seconds() / 60

                if time_diff <= SESSION_TIMEOUT_MINUTES:
                    current_session.append(event)
                else:
                    sessions.append(current_session)
                    current_session = [event]

        if current_session:
            sessions.append(current_session)

        daily_seconds = {}

        for session in sessions:
            if not session:
                continue

            session_start = session[0].event_time
            session_end = session[-1].event_time
            session_duration = (session_end - session_start).total_seconds()

            if session_duration > self.MAX_SESSION_HOURS * 3600:
                session_duration = self.MAX_SESSION_HOURS * 3600

            session_date = session_start.date()

            if session_date not in daily_seconds:
                daily_seconds[session_date] = 0
            daily_seconds[session_date] += session_duration

        return self._format_screen_time_result(user_id, start_date, end_date, daily_seconds)

    def get_api_timing_summary(
        self, hours: int, platform: str | None, app_version: str | None
    ) -> list[ApiTimingRowDTO]:
        """Aggregate real-user API latency from `api_request` events.

        Reuses the existing user_activity stream: the app's RUM interceptor
        sends events with event_name='api_request' and
        meta={endpoint, duration_ms, status}. Per-endpoint p50/p95, average and
        error rate are computed over the window directly in SQL (ordered-set
        aggregates), so the dashboard query is a single round-trip.

        A sample is an error when its status is not a 1xx-3xx code (covers
        4xx/5xx, network 0, and missing/garbage values).
        """
        sql = text(
            """
            SELECT
                meta->>'endpoint' AS endpoint,
                count(*) AS count,
                percentile_cont(0.5) WITHIN GROUP (
                    ORDER BY (meta->>'duration_ms')::float
                ) AS p50,
                percentile_cont(0.95) WITHIN GROUP (
                    ORDER BY (meta->>'duration_ms')::float
                ) AS p95,
                avg((meta->>'duration_ms')::float) AS avg,
                sum(
                    CASE WHEN (meta->>'status') ~ '^[1-3][0-9][0-9]$'
                         THEN 0 ELSE 1 END
                )::float / count(*) AS error_rate
            FROM user_activity
            WHERE event_name = 'api_request'
              AND event_time > now() - make_interval(hours => :hours)
              AND (meta->>'endpoint') IS NOT NULL
              AND (meta->>'duration_ms') ~ '^[0-9]+(\\.[0-9]+)?$'
              AND (:platform IS NULL OR platform = :platform)
              AND (:app_version IS NULL OR app_version = :app_version)
            GROUP BY meta->>'endpoint'
            ORDER BY p95 DESC
            """
        )
        rows = self._session.execute(
            sql,
            {"hours": hours, "platform": platform, "app_version": app_version},
        ).fetchall()
        return [
            ApiTimingRowDTO(
                endpoint=r.endpoint,
                count=int(r.count),
                p50_ms=round(float(r.p50 or 0), 1),
                p95_ms=round(float(r.p95 or 0), 1),
                avg_ms=round(float(r.avg or 0), 1),
                error_rate=round(float(r.error_rate or 0), 4),
            )
            for r in rows
        ]

    def get_payments_by_gateway(self, hours: int) -> list[PaymentByGatewayRowDTO]:
        """Paid-payment totals split by gateway over the window.

        Buckets google_play (recorded by the IAP verify + RTDN flows) vs
        freedompay (everything else). Only status='paid' counts as revenue —
        same definition the subscription activation uses.
        """
        sql = text(
            """
            SELECT
                CASE WHEN pg_payment_method = 'google_play'
                     THEN 'google_play' ELSE 'freedompay' END AS gateway,
                count(*) AS count,
                COALESCE(sum(amount), 0) AS total_amount
            FROM payments
            WHERE status = 'paid'
              AND created_at > now() - make_interval(hours => :hours)
            GROUP BY 1
            ORDER BY total_amount DESC
            """
        )
        rows = self._session.execute(sql, {"hours": hours}).fetchall()
        return [
            PaymentByGatewayRowDTO(
                gateway=r.gateway,
                count=int(r.count),
                total_amount=r.total_amount or 0,
            )
            for r in rows
        ]

    def get_user_screen_time_by_activity(
        self, user_id: UUID, start_date: date, end_date: date
    ) -> ScreenTimeByActivityDTO:
        events_query = (
            select(
                UserActivity.session_id,
                UserActivity.event_name,
                UserActivity.event_time,
            )
            .where(
                UserActivity.user_id == user_id,
                UserActivity.event_time >= start_date,
                UserActivity.event_time < end_date + timedelta(days=1),
            )
            .order_by(UserActivity.session_id, UserActivity.event_time)
        )

        events = self._session.execute(events_query).all()

        if not events:
            empty_screen_time = self._get_empty_screen_time(user_id, start_date, end_date)
            return ScreenTimeByActivityDTO(
                ent_subject=empty_screen_time,
                ent_full=empty_screen_time,
                trainer=empty_screen_time,
                daily=empty_screen_time,
                other=empty_screen_time,
                total=empty_screen_time,
            )

        sessions = {}
        for event in events:
            session_id = event.session_id
            if session_id not in sessions:
                sessions[session_id] = []
            sessions[session_id].append(event)

        daily_seconds_by_activity = {
            "ent_subject": {},
            "ent_full": {},
            "trainer": {},
            "daily": {},
            "other": {},
            "total": {},
        }

        for _, session_events in sessions.items():
            if not session_events or len(session_events) < 2:
                continue

            session_events.sort(key=lambda x: x.event_time)

            for i in range(len(session_events) - 1):
                current_event = session_events[i]
                next_event = session_events[i + 1]

                time_diff = (next_event.event_time - current_event.event_time).total_seconds()

                if time_diff > self.MAX_SESSION_HOURS * 3600:
                    continue

                activity = self._classify_event(current_event.event_name)
                session_date = current_event.event_time.date()

                if session_date not in daily_seconds_by_activity[activity]:
                    daily_seconds_by_activity[activity][session_date] = 0
                daily_seconds_by_activity[activity][session_date] += time_diff

                if session_date not in daily_seconds_by_activity["total"]:
                    daily_seconds_by_activity["total"][session_date] = 0
                daily_seconds_by_activity["total"][session_date] += time_diff

        result = {}
        for activity_type in [
            "ent_subject",
            "ent_full",
            "trainer",
            "daily",
            "other",
            "total",
        ]:
            result[activity_type] = self._format_screen_time_result(
                user_id, start_date, end_date, daily_seconds_by_activity[activity_type]
            )

        return ScreenTimeByActivityDTO(**result)

    def _get_empty_screen_time(self, user_id: UUID, start_date: date, end_date: date) -> UserScreenTimeDTO:
        daily_screen_times = []
        current_date = start_date

        while current_date <= end_date:
            daily_screen_times.append(
                DailyScreenTimeDTO(
                    date=current_date,
                    screen_time_seconds=0,
                    screen_time_formatted="0s",
                )
            )
            current_date += timedelta(days=1)

        return UserScreenTimeDTO(
            user_id=str(user_id),
            period_start=start_date,
            period_end=end_date,
            total_screen_time_seconds=0,
            average_daily_screen_time_seconds=0,
            daily_screen_times=daily_screen_times,
        )

    def _format_screen_time_result(
        self, user_id: UUID, start_date: date, end_date: date, daily_seconds: dict
    ) -> UserScreenTimeDTO:
        daily_screen_times = []
        total_seconds = 0
        days_count = (end_date - start_date).days + 1

        current_date = start_date
        while current_date <= end_date:
            seconds = daily_seconds.get(current_date, 0)
            total_seconds += seconds

            formatted = self._format_seconds(seconds)

            daily_screen_times.append(
                DailyScreenTimeDTO(
                    date=current_date,
                    screen_time_seconds=int(seconds),
                    screen_time_formatted=formatted,
                )
            )

            current_date += timedelta(days=1)

        return UserScreenTimeDTO(
            user_id=str(user_id),
            period_start=start_date,
            period_end=end_date,
            total_screen_time_seconds=int(total_seconds),
            average_daily_screen_time_seconds=(int(total_seconds / days_count) if days_count > 0 else 0),
            daily_screen_times=daily_screen_times,
        )

    def _format_seconds(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            if secs == 0:
                return f"{minutes}m"
            else:
                return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

    def _classify_event(self, event_name: str) -> str:
        """Классифицирует событие по типу активности"""
        event_name_lower = event_name.lower()

        if "ent_subject" in event_name_lower:
            return "ent_subject"
        elif "ent_full" in event_name_lower:
            return "ent_full"
        elif "trainer" in event_name_lower and not event_name_lower.startswith("ent"):
            return "trainer"
        elif "daily" in event_name_lower:
            return "daily"
        elif "ent" in event_name_lower:
            return "ent_subject"
        else:
            return "other"

    def _format_screen_time_result(
        self, user_id: UUID, start_date: date, end_date: date, daily_seconds: dict
    ) -> UserScreenTimeDTO:
        daily_screen_times = []
        total_seconds = 0
        days_count = (end_date - start_date).days + 1

        current_date = start_date
        while current_date <= end_date:
            seconds = daily_seconds.get(current_date, 0)
            total_seconds += seconds

            formatted = self._format_seconds(seconds)

            daily_screen_times.append(
                DailyScreenTimeDTO(
                    date=current_date,
                    screen_time_seconds=int(seconds),
                    screen_time_formatted=formatted,
                )
            )

            current_date += timedelta(days=1)

        return UserScreenTimeDTO(
            user_id=str(user_id),
            period_start=start_date,
            period_end=end_date,
            total_screen_time_seconds=int(total_seconds),
            average_daily_screen_time_seconds=(int(total_seconds / days_count) if days_count > 0 else 0),
            daily_screen_times=daily_screen_times,
        )
