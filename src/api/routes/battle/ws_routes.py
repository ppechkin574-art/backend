from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from api.routes.battle.manager import battle_manager
from battle.models import BattleSession
from battle.service import (
    BATTLE_TIME_SECONDS,
    BattleService,
    questions_for_client,
)
from database import Database
from settings import Settings

router = APIRouter(tags=["Battle WS"])
logger = logging.getLogger(__name__)

# Module-level container reference set on first WS connection (app.state.container)
_container = None


def _make_db_session():
    if _container is not None:
        return _container.database().session
    settings = Settings()  # noqa
    db = Database(settings.database)
    return db.session


def _make_redis():
    if _container is not None:
        return _container.redis()
    from api.dependencies import get_redis
    return get_redis()


async def _run_bot_task(
    session_id: str,
    player1_id: str,
    questions: list[dict],
    win_rate: int,
) -> None:
    """Background task simulating the bot answering all questions."""
    for q in questions:
        delay = random.uniform(1.5, 8.0)
        await asyncio.sleep(delay)

        db = _make_db_session()
        # Keep db open for _finish_and_notify when all questions answered.
        finish_session = None
        finish_svc = None
        try:
            redis = _make_redis()
            svc = BattleService(db, redis)
            session = db.query(BattleSession).filter(
                BattleSession.id == uuid.UUID(session_id),
                BattleSession.status == "active",
            ).first()
            if not session:
                break

            correct_variant_id = q.get("correct_variant_id")
            if correct_variant_id and random.randint(1, 100) <= win_rate:
                chosen = correct_variant_id
            else:
                wrong = [v["id"] for v in q["variants"] if v["id"] != correct_variant_id]
                chosen = random.choice(wrong) if wrong else correct_variant_id

            bot_id = f"bot:{session.bot_name}"
            svc.record_answer(session, bot_id, q["id"], chosen)
            db.refresh(session)

            await battle_manager.send_to(session_id, player1_id, {
                "type": "opponent_answered",
                "question_id": q["id"],
                "opponent_score": session.player2_score,
            })

            db.refresh(session)
            if svc.all_answered(session):
                finish_session = session
                finish_svc = svc

        except Exception:
            logger.exception("Bot task error for session %s q=%s", session_id, q["id"])
        finally:
            if finish_session is None:
                db.close()

        if finish_session is not None:
            try:
                await _finish_and_notify(finish_session, finish_svc, session_id, player1_id)
            except Exception:
                logger.exception("Bot finish_and_notify error for session %s", session_id)
            finally:
                db.close()
            break


async def _finish_and_notify(
    session: BattleSession,
    svc: BattleService,
    session_id: str,
    player1_id: str,
) -> None:
    if session.status != "active":
        return
    svc.finish_session(session)
    p1 = session.player1_score
    p2 = session.player2_score
    winner_id = session.winner_id

    if winner_id == player1_id:
        outcome = "me"
    elif winner_id == "draw":
        outcome = "draw"
    else:
        outcome = "opponent"

    await battle_manager.send_to(session_id, player1_id, {
        "type": "battle_end",
        "my_score": p1,
        "opponent_score": p2,
        "winner": outcome,
        "stars_earned": session.stars_player1,
    })


async def _timer_task(session_id: str, player1_id: str, duration: int) -> None:
    await asyncio.sleep(duration)
    db = _make_db_session()
    try:
        redis = _make_redis()
        svc = BattleService(db, redis)
        session = db.query(BattleSession).filter(
            BattleSession.id == uuid.UUID(session_id),
            BattleSession.status == "active",
        ).first()
        if session:
            await _finish_and_notify(session, svc, session_id, player1_id)
    except Exception:
        logger.exception("Timer task error for session %s", session_id)
    finally:
        db.close()


@router.websocket("/ws/battle/{session_id}")
async def battle_ws(websocket: WebSocket, session_id: str):
    """
    WebSocket battle endpoint.
    Auth: pass Keycloak access_token as query param `token`.
    """
    global _container

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Extract user_id from Keycloak JWT using the app-level IDP client
    try:
        container = websocket.app.state.container
        if _container is None:
            _container = container
        idp_client = container.identity_provider_client()
        user_uuid = idp_client.get_user_sub_from_token(token)
        user_id = str(user_uuid)
    except Exception:
        logger.warning("Battle WS: invalid token for session %s", session_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Load session
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db = _make_db_session()
    redis = _make_redis()

    session = db.query(BattleSession).filter(
        BattleSession.id == session_uuid,
        BattleSession.player1_id == user_id,
    ).first()

    if not session:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        db.close()
        return

    await battle_manager.connect(session_id, user_id, websocket)

    svc = BattleService(db, redis)
    if session.status == "searching":
        session = svc.activate_bot_session(session_id)
        if not session:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            battle_manager.disconnect(session_id, user_id)
            db.close()
            return

    questions = session.question_data.get("questions", [])
    lang = websocket.query_params.get("lang", "ru")
    client_questions = questions_for_client(questions, lang=lang)

    # Reset scores so every WS game starts from 0-0 regardless of prior state.
    session.player1_score = 0
    session.player2_score = 0
    db.commit()

    await battle_manager.send_to(session_id, user_id, {
        "type": "battle_start",
        "session_id": session_id,
        "total_time": BATTLE_TIME_SECONDS,
        "questions": [q.model_dump() for q in client_questions],
        "opponent": {
            "name": session.bot_name or "Соперник",
            "is_bot": False,
        },
        "my_score": 0,
        "opponent_score": 0,
    })

    bot_task = None
    if session.is_bot:
        bot_task = asyncio.create_task(
            _run_bot_task(session_id, user_id, questions, session.bot_win_rate or 50)
        )

    timer_task = asyncio.create_task(_timer_task(session_id, user_id, BATTLE_TIME_SECONDS))

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "pong":
                continue

            elif msg_type == "answer":
                q_id = msg.get("question_id")
                v_id = msg.get("variant_id")
                if not q_id:
                    continue

                db.refresh(session)
                if session.status != "active":
                    break

                is_correct, correct_v_id = svc.record_answer(session, user_id, q_id, v_id)
                db.refresh(session)

                await battle_manager.send_to(session_id, user_id, {
                    "type": "question_result",
                    "question_id": q_id,
                    "is_correct": is_correct,
                    "correct_variant_id": correct_v_id,
                    "my_score": session.player1_score,
                    "opponent_score": session.player2_score,
                })

                db.refresh(session)
                if svc.all_answered(session):
                    await _finish_and_notify(session, svc, session_id, user_id)
                    break

            elif msg_type == "forfeit":
                db.refresh(session)
                svc.forfeit(session, user_id)
                await battle_manager.send_to(session_id, user_id, {
                    "type": "battle_end",
                    "my_score": session.player1_score,
                    "opponent_score": session.player2_score,
                    "winner": "opponent",
                    "stars_earned": 0,
                })
                break

    except WebSocketDisconnect:
        logger.info("Battle WS disconnected: session=%s user=%s", session_id, user_id[:8])
    except Exception:
        logger.exception("Battle WS error: session=%s", session_id)
    finally:
        if bot_task and not bot_task.done():
            bot_task.cancel()
        if timer_task and not timer_task.done():
            timer_task.cancel()
        battle_manager.disconnect(session_id, user_id)
        db.close()
