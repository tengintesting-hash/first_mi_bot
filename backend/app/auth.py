import hashlib
import hmac
import os
from typing import Dict
from urllib.parse import parse_qsl

from fastapi import HTTPException, status


def parse_init_data(init_data: str) -> Dict[str, str]:
    return dict(parse_qsl(init_data, keep_blank_values=True))


def validate_telegram_init_data(init_data: str) -> Dict[str, str]:
    data = parse_init_data(init_data)
    if "hash" not in data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing hash")
    received_hash = data.pop("hash")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    bot_token = os.getenv("BOT_TOKEN", "")
    if not bot_token:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="BOT_TOKEN missing")
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid initData")
    return data


def require_admin(telegram_id: int) -> None:
    admin_ids = os.getenv("ADMIN_IDS", "")
    allowed = {item.strip() for item in admin_ids.split(",") if item.strip()}
    if not allowed or str(telegram_id) not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
