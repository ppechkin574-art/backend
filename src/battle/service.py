from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from redis import Redis
from sqlalchemy import func, text
from sqlalchemy.orm import Session, joinedload

from bank.models import Transaction, TransactionStatus, TransactionType, UserBankAccount
from battle.models import BattleAnswer, BattleSession
from battle.schemas import (
    BattleOpponent,
    BattleQuestion,
    BattleVariant,
    JoinQueueResponse,
    SessionStatusResponse,
)
from quiz.dtos.enums import BlockType
from quiz.models.edu_content import Question, Subject, Variant
from quiz.models.text_blocks import TextBlock, TextBlockLink

logger = logging.getLogger(__name__)

ALMATY_TZ = timezone(timedelta(hours=5))
BATTLE_STARS_WIN = 50
BATTLE_STARS_DRAW = 25
BATTLE_QUESTIONS_PER_SUBJECT = 5
BATTLE_TIME_SECONDS = 300
BOT_NAMES = [
    "Айгерім Н.", "Нұрлан Б.", "Дина С.", "Арман Қ.", "Зарина Т.",
    "Бекзат М.", "Гүлназ Е.", "Дәурен А.", "Меруерт О.", "Тимур Р.",
    "Ақнұр Ж.", "Сейткали Б.", "Аружан Д.", "Нұрбек С.", "Камила Ж.",
]

LEADERBOARD_KEY_PREFIX = "battle:leaderboard:"
LEADERBOARD_WINS_KEY_PREFIX = "battle:leaderboard:wins:"
LEADERBOARD_LOSSES_KEY_PREFIX = "battle:leaderboard:losses:"
QUEUE_KEY_PREFIX = "battle:queue:"
USER_SESSION_KEY_PREFIX = "battle:user_session:"


def _today_key() -> str:
    now = datetime.now(ALMATY_TZ)
    return now.strftime("%Y-%m-%d")


def _get_text_from_blocks(link: TextBlockLink | None) -> str:
    if not link or not link.blocks:
        return ""
    blocks = sorted(link.blocks, key=lambda b: b.order)
    return " ".join(b.value or "" for b in blocks if b.value and b.type != BlockType.media).strip()


def _get_image_url_from_blocks(link: TextBlockLink | None) -> str | None:
    if not link or not link.blocks:
        return None
    for b in sorted(link.blocks, key=lambda b: b.order):
        if b.type == BlockType.media and b.value:
            return b.value
    return None


def _format_question(q: Question, subject_name: str) -> dict:
    correct_variant_id = None
    variants = []
    text_ru = _get_text_from_blocks(q.link) if q.link else ""
    text_kk = q.question_text_kk or text_ru
    for v in q.variants or []:
        vru = _get_text_from_blocks(v.link) if v.link else ""
        vkk = v.variant_text_kk or vru
        variants.append({"id": v.id, "text_ru": vru, "text_kk": vkk})
        if v.is_correct:
            correct_variant_id = v.id
    return {
        "id": q.id,
        "subject_id": q.subject_id,
        "subject_name": subject_name,
        "text_ru": text_ru,
        "text_kk": text_kk,
        "variants": variants,
        "correct_variant_id": correct_variant_id,
        "explanation_ru": q.explanation_ru or q.explanation_kk,
        "explanation_kk": q.explanation_kk or q.explanation_ru,
        "image_url": _get_image_url_from_blocks(q.link),
    }


def fetch_battle_questions(db: Session, subject_ids: list[int]) -> list[dict]:
    """Fetch BATTLE_QUESTIONS_PER_SUBJECT random questions per subject with text."""
    all_questions = []
    subject_names: dict[int, str] = {}

    subjects = db.query(Subject).filter(Subject.id.in_(subject_ids)).all()
    for s in subjects:
        subject_names[s.id] = s.name

    for sid in subject_ids:
        question_ids = (
            db.query(Question.id)
            .filter(Question.subject_id == sid)
            .order_by(func.random())
            .limit(BATTLE_QUESTIONS_PER_SUBJECT)
            .all()
        )
        if not question_ids:
            continue
        qids = [r[0] for r in question_ids]
        questions = (
            db.query(Question)
            .filter(Question.id.in_(qids))
            .options(
                joinedload(Question.variants).joinedload(Variant.link).joinedload(TextBlockLink.blocks),
                joinedload(Question.link).joinedload(TextBlockLink.blocks),
            )
            .all()
        )
        sname = subject_names.get(sid, "")
        for q in questions:
            all_questions.append(_format_question(q, sname))

    random.shuffle(all_questions)
    return all_questions


def build_correct_answers(questions: list[dict]) -> dict[str, int]:
    return {str(q["id"]): q["correct_variant_id"] for q in questions if q.get("correct_variant_id")}


def questions_for_client(questions: list[dict], lang: str = "ru") -> list[BattleQuestion]:
    """Strip correct_variant_id before sending to client. lang: 'ru' or 'kk'."""
    result = []
    for q in questions:
        text = q.get(f"text_{lang}") or q.get("text_ru") or q.get("text") or ""
        expl = q.get(f"explanation_{lang}") or q.get("explanation_ru") or q.get("explanation")
        result.append(BattleQuestion(
            id=q["id"],
            subject_id=q["subject_id"],
            subject_name=q["subject_name"],
            text=text,
            variants=[
                BattleVariant(id=v["id"], text=v.get(f"text_{lang}") or v.get("text_ru") or v.get("text") or "")
                for v in q["variants"]
            ],
            explanation=expl,
            image_url=q.get("image_url"),
        ))
    return result


class BattleService:
    def __init__(self, db: Session, redis: Redis):
        self.db = db
        self.redis = redis

    def _subject_key(self, subject_ids: list[int]) -> str:
        return ":".join(str(s) for s in sorted(subject_ids))

    def join_or_create(self, user_id: str, subject_ids: list[int]) -> JoinQueueResponse:
        user_id = str(user_id)  # caller may pass UUID object; normalize to str
        # Check if user already in an active session
        existing_key = f"{USER_SESSION_KEY_PREFIX}{user_id}"
        existing_session_id = self.redis.get(existing_key)
        if existing_session_id:
            sid = existing_session_id.decode() if isinstance(existing_session_id, bytes) else existing_session_id
            try:
                existing_uuid = uuid.UUID(sid)
            except (ValueError, AttributeError):
                # Corrupted Redis value — clear it and continue to create a fresh session
                logger.warning("join_or_create: invalid UUID in Redis for user %s: %r — clearing", user_id, sid)
                self.redis.delete(existing_key)
                existing_uuid = None

            if existing_uuid is not None:
                session = self.db.query(BattleSession).filter(
                    BattleSession.id == existing_uuid,
                    BattleSession.status.in_(["searching", "active"]),
                ).first()
                if session:
                    return JoinQueueResponse(session_id=sid, status=session.status)

        # Look for opponent in queue
        queue_key = f"{QUEUE_KEY_PREFIX}{self._subject_key(subject_ids)}"
        raw = self.redis.lrange(queue_key, 0, -1)
        opponent_id = None
        opponent_session_id = None

        for entry_bytes in raw:
            try:
                entry = json.loads(entry_bytes.decode() if isinstance(entry_bytes, bytes) else entry_bytes)
            except (ValueError, UnicodeDecodeError):
                logger.warning("join_or_create: malformed queue entry — skipping")
                continue
            if entry["user_id"] != user_id:
                # Remove from queue
                self.redis.lrem(queue_key, 1, entry_bytes)
                opponent_id = entry["user_id"]
                opponent_session_id = entry["session_id"]
                break

        if opponent_id and opponent_session_id:
            # Found real opponent — activate their session and create ours as linked
            try:
                opp_uuid = uuid.UUID(opponent_session_id)
            except (ValueError, AttributeError):
                logger.warning("join_or_create: invalid opponent session UUID %r — falling back to bot", opponent_session_id)
                opp_uuid = None

            opp_session = self.db.query(BattleSession).filter(
                BattleSession.id == opp_uuid,
                BattleSession.status == "searching",
            ).first() if opp_uuid is not None else None

            if opp_session:
                # Use same questions for both
                questions = fetch_battle_questions(self.db, subject_ids)
                question_data = {
                    "questions": questions,
                    "correct_answers": build_correct_answers(questions),
                }
                now = datetime.now(UTC)

                # Update opponent's session to be pvp active
                opp_session.player2_id = user_id
                opp_session.is_bot = False
                opp_session.question_data = question_data
                opp_session.status = "active"
                opp_session.started_at = now

                # Create a mirrored session for the new user
                new_session = BattleSession(
                    id=uuid.uuid4(),
                    player1_id=user_id,
                    player2_id=opponent_id,
                    is_bot=False,
                    subject_ids=subject_ids,
                    question_data=question_data,
                    status="active",
                    started_at=now,
                )
                self.db.add(new_session)
                self.db.commit()

                # Store session mapping in Redis (TTL 2h)
                sid_str = str(new_session.id)
                self.redis.setex(f"{USER_SESSION_KEY_PREFIX}{user_id}", 7200, sid_str)

                # Notify opponent session is active (stored in Redis for polling)
                self.redis.setex(
                    f"battle:pvp_link:{opp_session.id}",
                    7200,
                    str(new_session.id),
                )
                self.redis.setex(
                    f"battle:pvp_link:{new_session.id}",
                    7200,
                    str(opp_session.id),
                )

                return JoinQueueResponse(session_id=sid_str, status="active")

        # No opponent found — create a searching session
        questions = fetch_battle_questions(self.db, subject_ids)
        question_data = {
            "questions": questions,
            "correct_answers": build_correct_answers(questions),
        }
        win_rate = random.randint(50, 62)  # mid-tier only
        bot_name = random.choice(BOT_NAMES)

        bot_player_id = f"bot:{bot_name}"
        session = BattleSession(
            id=uuid.uuid4(),
            player1_id=user_id,
            player2_id=bot_player_id,
            is_bot=True,
            bot_name=bot_name,
            bot_win_rate=win_rate,
            subject_ids=subject_ids,
            question_data=question_data,
            status="searching",
        )
        self.db.add(session)
        self.db.commit()

        session_id_str = str(session.id)
        self.redis.setex(f"{USER_SESSION_KEY_PREFIX}{user_id}", 7200, session_id_str)

        # Add to queue for potential real PvP
        queue_entry = json.dumps({"user_id": user_id, "session_id": session_id_str})
        self.redis.rpush(queue_key, queue_entry)
        self.redis.expire(queue_key, 120)  # queue entry valid 2 min

        return JoinQueueResponse(session_id=session_id_str, status="searching")

    def activate_bot_session(self, session_id: str) -> BattleSession | None:
        """Transition a searching session to active (bot opponent)."""
        session = self.db.query(BattleSession).filter(
            BattleSession.id == uuid.UUID(session_id),
            BattleSession.status == "searching",
        ).first()
        if not session:
            return None
        session.status = "active"
        session.started_at = datetime.now(UTC)
        self.db.commit()
        return session

    def get_session(self, session_id: str, user_id: str) -> BattleSession | None:
        try:
            sid = uuid.UUID(session_id)
        except ValueError:
            return None
        return self.db.query(BattleSession).filter(
            BattleSession.id == sid,
            BattleSession.player1_id == str(user_id),
        ).first()

    def record_answer(
        self,
        session: BattleSession,
        player_id: str,
        question_id: int,
        variant_id: int | None,
    ) -> tuple[bool, int]:
        """
        Records an answer and returns (is_correct, correct_variant_id).
        Also updates player score in-session.
        """
        correct_answers: dict = session.question_data.get("correct_answers", {})
        correct_variant_id = correct_answers.get(str(question_id))

        # Deduplicate: if this player already answered this question, skip scoring.
        existing = self.db.query(BattleAnswer).filter_by(
            session_id=session.id,
            player_id=player_id,
            question_id=question_id,
        ).first()
        if existing:
            return existing.is_correct, correct_variant_id or 0

        is_correct = variant_id is not None and variant_id == correct_variant_id

        answer = BattleAnswer(
            session_id=session.id,
            player_id=player_id,
            question_id=question_id,
            variant_id=variant_id,
            is_correct=is_correct,
            answered_at=datetime.now(UTC),
        )
        self.db.add(answer)

        if is_correct:
            if player_id == session.player1_id:
                session.player1_score += 1
            else:
                session.player2_score += 1

        self.db.commit()
        return is_correct, correct_variant_id or 0

    def all_answered(self, session: BattleSession) -> bool:
        """True when both players have answered all questions."""
        questions = session.question_data.get("questions", [])
        total = len(questions)
        if total == 0:
            return True
        answers = self.db.query(BattleAnswer).filter(BattleAnswer.session_id == session.id).all()
        player2 = session.player2_id or f"bot:{session.bot_name}"
        player_ids = {session.player1_id, player2}
        by_player: dict[str, set[int]] = {p: set() for p in player_ids}
        for a in answers:
            if a.player_id in by_player:
                by_player[a.player_id].add(a.question_id)
        return all(len(v) >= total for v in by_player.values())

    def _credit_stars_to_bank(self, player_id: str, stars: int, description: str) -> None:
        """Credit battle stars to the player's bank balance (within the current DB transaction)."""
        if stars <= 0:
            return
        try:
            player_uuid = uuid.UUID(player_id)
        except ValueError:
            return  # bot player_id is not a UUID
        try:
            acct = self.db.query(UserBankAccount).filter(
                UserBankAccount.student_guid == player_uuid
            ).first()
            if acct is None:
                logger.debug("No bank account for player %s, skipping stars credit", player_id)
                return
            acct.balance += stars
            self.db.add(Transaction(
                guid=uuid.uuid4(),
                account_guid=acct.guid,
                amount=stars,
                description=description,
                type=TransactionType.deposit,
                status=TransactionStatus.completed,
            ))
        except Exception:
            logger.exception("Failed to credit battle stars for player %s", player_id)

    def finish_session(self, session: BattleSession) -> None:
        """Compute winner, award stars, credit bank balance, update leaderboard."""
        p1 = session.player1_score
        p2 = session.player2_score

        if p1 > p2:
            session.winner_id = session.player1_id
            session.stars_player1 = BATTLE_STARS_WIN
            session.stars_player2 = 0
            bank_desc = "Победа в баттле"
        elif p2 > p1:
            session.winner_id = session.player2_id or "bot"
            session.stars_player1 = 0
            session.stars_player2 = BATTLE_STARS_WIN
            bank_desc = "Поражение в баттле"
        else:
            session.winner_id = "draw"
            session.stars_player1 = BATTLE_STARS_DRAW
            session.stars_player2 = BATTLE_STARS_DRAW
            bank_desc = "Ничья в баттле"

        session.status = "finished"
        session.finished_at = datetime.now(UTC)

        # Credit stars to player's bank account (same DB transaction as session update)
        self._credit_stars_to_bank(session.player1_id, session.stars_player1, bank_desc)

        self.db.commit()

        # Clear the Redis session key so the next joinQueue creates a fresh session
        # immediately instead of waiting for the 2-hour TTL to expire.
        self.redis.delete(f"{USER_SESSION_KEY_PREFIX}{session.player1_id}")

        # Update leaderboard for player1 (real user)
        self._update_leaderboard(
            user_id=session.player1_id,
            stars=session.stars_player1,
            won=(session.winner_id == session.player1_id),
        )

    def _update_leaderboard(self, user_id: str, stars: int, won: bool) -> None:
        day_key = _today_key()
        lb_key = f"{LEADERBOARD_KEY_PREFIX}{day_key}"
        wins_key = f"{LEADERBOARD_WINS_KEY_PREFIX}{day_key}"
        losses_key = f"{LEADERBOARD_LOSSES_KEY_PREFIX}{day_key}"

        # Add stars (ZINCRBY adds to existing score)
        if stars > 0:
            self.redis.zincrby(lb_key, stars, user_id)
        self.redis.expire(lb_key, 172800)  # 48h

        if won:
            self.redis.hincrby(wins_key, user_id, 1)
        else:
            self.redis.hincrby(losses_key, user_id, 1)
        self.redis.expire(wins_key, 172800)
        self.redis.expire(losses_key, 172800)

    def get_daily_leaderboard(self, my_user_id: str | None = None) -> dict:
        day_key = _today_key()
        lb_key = f"{LEADERBOARD_KEY_PREFIX}{day_key}"
        wins_key = f"{LEADERBOARD_WINS_KEY_PREFIX}{day_key}"
        losses_key = f"{LEADERBOARD_LOSSES_KEY_PREFIX}{day_key}"

        top = self.redis.zrevrangebyscore(lb_key, "+inf", "-inf", withscores=True, start=0, num=100)

        all_user_ids = [uid.decode() if isinstance(uid, bytes) else uid for uid, _ in top]

        wins_map: dict[str, int] = {}
        losses_map: dict[str, int] = {}
        if all_user_ids:
            wins_raw = self.redis.hmget(wins_key, all_user_ids)
            losses_raw = self.redis.hmget(losses_key, all_user_ids)
            for uid, w, l in zip(all_user_ids, wins_raw, losses_raw):
                wins_map[uid] = int(w or 0)
                losses_map[uid] = int(l or 0)

        entries = []
        my_entry = None
        for rank, (uid_bytes, score) in enumerate(top, 1):
            uid = uid_bytes.decode() if isinstance(uid_bytes, bytes) else uid_bytes
            entry = {
                "rank": rank,
                "user_id": uid,
                "name": uid,  # caller resolves display names
                "stars_today": int(score),
                "wins": wins_map.get(uid, 0),
                "losses": losses_map.get(uid, 0),
            }
            entries.append(entry)
            if uid == my_user_id:
                my_entry = entry

        return {"date": day_key, "entries": entries, "my_entry": my_entry}

    def forfeit(self, session: BattleSession, user_id: str) -> None:
        user_id = str(user_id)  # normalize UUID → str
        if session.status != "active":
            return
        # Opponent wins
        if user_id == session.player1_id:
            session.winner_id = session.player2_id or "bot"
            session.stars_player1 = 0
            session.stars_player2 = BATTLE_STARS_WIN
        else:
            session.winner_id = session.player1_id
            session.stars_player1 = BATTLE_STARS_WIN
            session.stars_player2 = 0
        session.status = "finished"
        session.finished_at = datetime.now(UTC)
        self.db.commit()

        self._update_leaderboard(
            user_id=session.player1_id,
            stars=session.stars_player1,
            won=(session.winner_id == session.player1_id),
        )
