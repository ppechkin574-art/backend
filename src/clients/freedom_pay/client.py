import hashlib
import logging
import uuid
from typing import Any

import httpx
from fastapi import HTTPException

from database.database import Session
from payments.models import Payment

logger = logging.getLogger(__name__)


def make_order_id(session: Session) -> str:
    logger.debug("Generating order ID")
    while True:
        order_id = str(uuid.uuid4())
        existing = session.query(Payment).filter(Payment.order_id == order_id).first()
        if not existing:
            logger.debug("Generated unique order ID: %s", order_id)
            return order_id


def make_pg_sig(params: dict[str, Any], script_name: str, secret: str) -> str:
    """
    - исключаем pg_sig и пустые значения
    - сортируем ключи
    - конкатенируем значения через ';'
    - добавляем ';' + secret в конец строки
    - считаем MD5 (ключ = secret, сообщение = полученная строка)
    - возвращаем hex lower
    """
    logger.debug("Generating signature for script: %s", script_name)
    data = {k: v for k, v in params.items() if k != "pg_sig" and v is not None and str(v) != ""}
    keys = sorted(data.keys())
    values = [str(data[k]) for k in keys]
    message = ";".join(values)
    message_with_secret = f"{script_name};{message};{secret}" if message != "" else secret
    sig = hashlib.md5(message_with_secret.encode("utf-8")).hexdigest()  # noqa: S324
    logger.debug("Signature generated: %s", sig)
    return sig


def verify_pg_sig(params: dict[str, Any], script_name: str, secret: str, incoming_sig: str) -> bool:
    logger.debug("Verifying signature for script: %s", script_name)
    if not incoming_sig:
        logger.warning("No signature provided for verification")
        return False
    expected = make_pg_sig(params, script_name, secret)
    logger.debug("Expected signature: %s, incoming: %s", expected, incoming_sig)
    result = expected == (incoming_sig or "")
    logger.debug("Signature verification result: %s", result)
    return result


async def post_to_fp(url: str, params: dict[str, Any], script_name: str, secret_key: str) -> tuple[str, dict, int]:
    logger.info("Sending request to FreedomPay: %s", script_name)
    if "pg_salt" not in params or not params.get("pg_salt"):
        params["pg_salt"] = uuid.uuid4().hex
        logger.debug("Generated salt: %s", params["pg_salt"])

    params["pg_sig"] = make_pg_sig(params, script_name, secret_key)

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        logger.debug("Sending POST request to: %s", url)
        logger.debug(
            "Request params: %s",
            {k: v for k, v in params.items() if k not in ["pg_sig"]},
        )
        r = await client.post(url, data=params)
        status = r.status_code
        headers = dict(r.headers)
        try:
            body_text = r.text
        except Exception:
            body_text = r.content.decode("utf-8", "replace")

        logger.info(
            "FreedomPay response - Status: %s, Content-Type: %s",
            status,
            headers.get("content-type"),
        )
        logger.debug("Response body: %s", body_text[:1000])

        if status != 200:
            logger.exception("FreedomPay error: Status %s, Response: %s", status, body_text)
            raise HTTPException(status_code=status, detail=f"FreedomPay error: {body_text}")

        return body_text, headers, status


async def get_payment_info(
    merchant_id: str, url: str, payment_id: str, script_name: str, secret_key: str
) -> tuple[str, dict, int]:
    """
    Функция для получения информации о платеже из FreedomPay через метод get_status3.php
    """
    logger.info("Getting payment info from FreedomPay via get_status3.php")

    params = {
        "pg_merchant_id": merchant_id,
        "pg_payment_id": payment_id,
        "pg_salt": uuid.uuid4().hex,
    }

    return await post_to_fp(url, params, script_name, secret_key)
