import hmac
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .auth import require_admin, validate_telegram_init_data
from .db import db_cursor, init_db

app = FastAPI(title="Casino Offers API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthRequest(BaseModel):
    initData: str = Field(..., alias="initData")


class WithdrawRequest(BaseModel):
    amount_pro: int = 0
    amount_usd: float = 0.0
    details: Optional[str] = None


class TaskPayload(BaseModel):
    title: str
    type: str
    display_type: str
    reward_pro: int = 0
    reward_usd: float = 0.0
    channel_id: Optional[int] = None
    offer_url: Optional[str] = None
    is_active: int = 1


class ChannelPayload(BaseModel):
    title: str
    telegram_id: str
    url: str
    required: int = 1


class UserUpdatePayload(BaseModel):
    is_blocked: Optional[int] = None
    pro_balance: Optional[int] = None
    usd_balance: Optional[float] = None


class OfferPayload(BaseModel):
    title: str
    offer_url: str
    reward_pro: int = 0
    reward_usd: float = 0.0
    display_type: str = "simple"
    is_active: int = 1


class BroadcastPayload(BaseModel):
    type: str
    text: Optional[str] = None
    media_url: Optional[str] = None
    button_text: Optional[str] = None
    button_url: Optional[str] = None
    audience: str


class PostbackPayload(BaseModel):
    event_id: str
    telegram_id: int
    status: str
    offer_id: Optional[int] = None
    payload: Dict[str, Any] = {}


def get_user_by_telegram_id(telegram_id: int) -> Optional[sqlite3.Row]:
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone()


def create_user(data: Dict[str, Any], referrer_id: Optional[int] = None) -> sqlite3.Row:
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO users (telegram_id, username, first_name, last_name, language_code, referrer_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(data.get("id")),
                data.get("username"),
                data.get("first_name"),
                data.get("last_name"),
                data.get("language_code"),
                referrer_id,
            ),
        )
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (int(data.get("id")),))
        return cursor.fetchone()


def update_balance(user_id: int, pro_delta: int = 0, usd_delta: float = 0.0, tx_type: str = "") -> None:
    with db_cursor() as cursor:
        cursor.execute(
            "UPDATE users SET pro_balance = pro_balance + ?, usd_balance = usd_balance + ? WHERE id = ?",
            (pro_delta, usd_delta, user_id),
        )
        cursor.execute(
            "INSERT INTO transactions (user_id, amount_pro, amount_usd, type) VALUES (?, ?, ?, ?)",
            (user_id, pro_delta, usd_delta, tx_type),
        )


def require_user(x_telegram_id: Optional[int] = Header(None)) -> sqlite3.Row:
    if not x_telegram_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Telegram ID")
    user = get_user_by_telegram_id(int(x_telegram_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user["is_blocked"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account blocked")
    return user


@app.on_event("startup")
async def startup() -> None:
    init_db()


@app.post("/api/auth/telegram")
async def auth_telegram(payload: AuthRequest) -> Dict[str, Any]:
    data = validate_telegram_init_data(payload.initData)
    user_data = json.loads(data.get("user", "{}"))
    if not user_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user data")
    ref_param = data.get("start_param")
    referrer_id = None
    if ref_param and ref_param.startswith("ref_"):
        try:
            ref_tg_id = int(ref_param.split("ref_", 1)[1])
        except ValueError:
            ref_tg_id = None
        if ref_tg_id and ref_tg_id != user_data.get("id"):
            referrer = get_user_by_telegram_id(ref_tg_id)
            if referrer:
                referrer_id = referrer["id"]

    user = get_user_by_telegram_id(int(user_data.get("id")))
    if not user:
        user = create_user(user_data, referrer_id=referrer_id)
        if referrer_id:
            update_balance(referrer_id, pro_delta=1000, tx_type="invite_reward")
    return {"telegram_id": user["telegram_id"], "pro_balance": user["pro_balance"], "usd_balance": user["usd_balance"]}


@app.get("/api/offers")
async def list_offers(user: sqlite3.Row = Depends(require_user)) -> Dict[str, Any]:
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT tasks.*, channels.title as channel_title, channels.url as channel_url
            FROM tasks
            LEFT JOIN channels ON channels.id = tasks.channel_id
            WHERE tasks.is_active = 1
            ORDER BY CASE WHEN tasks.display_type = 'limited' THEN 0 ELSE 1 END, tasks.id
            """
        )
        tasks = [dict(row) for row in cursor.fetchall()]
    return {"tasks": tasks}


@app.get("/api/referrals")
async def referrals(user: sqlite3.Row = Depends(require_user)) -> Dict[str, Any]:
    with db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE referrer_id = ?", (user["id"],))
        total = cursor.fetchone()["total"]
    return {"total": total, "referral_link": f"https://t.me/{os.getenv('BOT_USERNAME', 'bot')}?start=ref_{user['telegram_id']}"}


@app.get("/api/wallet")
async def wallet(user: sqlite3.Row = Depends(require_user)) -> Dict[str, Any]:
    return {"pro_balance": user["pro_balance"], "usd_balance": user["usd_balance"]}


@app.post("/api/withdraw")
async def withdraw(payload: WithdrawRequest, user: sqlite3.Row = Depends(require_user)) -> Dict[str, Any]:
    with db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO withdrawals (user_id, amount_pro, amount_usd, details) VALUES (?, ?, ?, ?)",
            (user["id"], payload.amount_pro, payload.amount_usd, payload.details),
        )
    return {"status": "ok"}


@app.post("/api/game/play")
async def play_game(user: sqlite3.Row = Depends(require_user)) -> Dict[str, Any]:
    if not user["is_deposit"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Deposit required")
    return {"status": "ok", "message": "Game started"}


@app.post("/postback")
async def postback(request: Request) -> Dict[str, Any]:
    signature = request.headers.get("X-Signature", "")
    secret = os.getenv("POSTBACK_SECRET", "")
    body = await request.body()
    expected = hmac_sha256(secret.encode(), body)
    if not secret or not hmac_sha256_compare(signature, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    payload = PostbackPayload(**await request.json())
    with db_cursor() as cursor:
        cursor.execute("SELECT 1 FROM postbacks WHERE event_id = ?", (payload.event_id,))
        if cursor.fetchone():
            return {"status": "ignored"}
        cursor.execute(
            "INSERT INTO postbacks (event_id, status, payload) VALUES (?, ?, ?)",
            (payload.event_id, payload.status, json.dumps(payload.payload)),
        )

    user = get_user_by_telegram_id(payload.telegram_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.status == "registration":
        reward_task(payload.offer_id, user["id"])
    elif payload.status == "deposit":
        with db_cursor() as cursor:
            cursor.execute("UPDATE users SET is_deposit = 1 WHERE id = ?", (user["id"],))
        reward_task(payload.offer_id, user["id"])
        if user["referrer_id"]:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM transactions WHERE user_id = ? AND type = 'referrer_deposit_bonus' AND metadata = ?",
                    (user["referrer_id"], str(user["id"])),
                )
                if not cursor.fetchone():
                    cursor.execute(
                        "INSERT INTO transactions (user_id, amount_pro, type, metadata) VALUES (?, ?, ?, ?)",
                        (user["referrer_id"], 5000, "referrer_deposit_bonus", str(user["id"])),
                    )
                    cursor.execute(
                        "UPDATE users SET pro_balance = pro_balance + 5000 WHERE id = ?",
                        (user["referrer_id"],),
                    )
    return {"status": "ok"}


@app.get("/admin/transactions")
async def admin_transactions(x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM transactions ORDER BY created_at DESC")
        rows = [dict(row) for row in cursor.fetchall()]
    return {"transactions": rows}


@app.post("/admin/tasks")
async def admin_create_task(payload: TaskPayload, x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tasks (title, type, display_type, reward_pro, reward_usd, channel_id, offer_url, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.title,
                payload.type,
                payload.display_type,
                payload.reward_pro,
                payload.reward_usd,
                payload.channel_id,
                payload.offer_url,
                payload.is_active,
            ),
        )
        task_id = cursor.lastrowid
    return {"id": task_id}


@app.get("/admin/tasks")
async def admin_list_tasks(x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM tasks ORDER BY id DESC")
        rows = [dict(row) for row in cursor.fetchall()]
    return {"tasks": rows}


@app.put("/admin/tasks/{task_id}")
async def admin_update_task(task_id: int, payload: TaskPayload, x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    with db_cursor() as cursor:
        cursor.execute(
            """
            UPDATE tasks
            SET title = ?, type = ?, display_type = ?, reward_pro = ?, reward_usd = ?, channel_id = ?, offer_url = ?, is_active = ?
            WHERE id = ?
            """,
            (
                payload.title,
                payload.type,
                payload.display_type,
                payload.reward_pro,
                payload.reward_usd,
                payload.channel_id,
                payload.offer_url,
                payload.is_active,
                task_id,
            ),
        )
    return {"status": "ok"}


@app.delete("/admin/tasks/{task_id}")
async def admin_delete_task(task_id: int, x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return {"status": "ok"}


@app.post("/admin/channels")
async def admin_create_channel(payload: ChannelPayload, x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    with db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO channels (title, telegram_id, url, required) VALUES (?, ?, ?, ?)",
            (payload.title, payload.telegram_id, payload.url, payload.required),
        )
        channel_id = cursor.lastrowid
    return {"id": channel_id}


@app.get("/admin/channels")
async def admin_list_channels(x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM channels ORDER BY id DESC")
        rows = [dict(row) for row in cursor.fetchall()]
    return {"channels": rows}


@app.put("/admin/channels/{channel_id}")
async def admin_update_channel(channel_id: int, payload: ChannelPayload, x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    with db_cursor() as cursor:
        cursor.execute(
            "UPDATE channels SET title = ?, telegram_id = ?, url = ?, required = ? WHERE id = ?",
            (payload.title, payload.telegram_id, payload.url, payload.required, channel_id),
        )
    return {"status": "ok"}


@app.delete("/admin/channels/{channel_id}")
async def admin_delete_channel(channel_id: int, x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    return {"status": "ok"}


@app.get("/admin/users")
async def admin_list_users(x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
        rows = [dict(row) for row in cursor.fetchall()]
    return {"users": rows}


@app.put("/admin/users/{telegram_id}")
async def admin_update_user(telegram_id: int, payload: UserUpdatePayload, x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    fields = []
    values: List[Any] = []
    if payload.is_blocked is not None:
        fields.append("is_blocked = ?")
        values.append(payload.is_blocked)
    if payload.pro_balance is not None:
        fields.append("pro_balance = ?")
        values.append(payload.pro_balance)
    if payload.usd_balance is not None:
        fields.append("usd_balance = ?")
        values.append(payload.usd_balance)
    if not fields:
        return {"status": "noop"}
    values.append(telegram_id)
    with db_cursor() as cursor:
        cursor.execute(f"UPDATE users SET {', '.join(fields)} WHERE telegram_id = ?", values)
    return {"status": "ok"}


@app.post("/admin/offers")
async def admin_create_offer(payload: OfferPayload, x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    task = TaskPayload(
        title=payload.title,
        type="offer",
        display_type=payload.display_type,
        reward_pro=payload.reward_pro,
        reward_usd=payload.reward_usd,
        offer_url=payload.offer_url,
        is_active=payload.is_active,
    )
    return await admin_create_task(task, x_telegram_id)


@app.post("/admin/broadcast")
async def admin_broadcast(payload: BroadcastPayload, x_telegram_id: int = Header(...)) -> Dict[str, Any]:
    require_admin(x_telegram_id)
    with db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO broadcast_log (payload, audience) VALUES (?, ?)",
            (payload.json(), payload.audience),
        )
    return {"status": "queued"}


def reward_task(offer_id: Optional[int], user_id: int) -> None:
    if not offer_id:
        return
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (offer_id,))
        task = cursor.fetchone()
        if not task:
            return
        cursor.execute(
            "SELECT status FROM user_tasks WHERE user_id = ? AND task_id = ?",
            (user_id, offer_id),
        )
        existing = cursor.fetchone()
        if existing and existing["status"] == "completed":
            return
        cursor.execute(
            "REPLACE INTO user_tasks (user_id, task_id, status) VALUES (?, ?, 'completed')",
            (user_id, offer_id),
        )
        cursor.execute(
            "UPDATE users SET pro_balance = pro_balance + ?, usd_balance = usd_balance + ? WHERE id = ?",
            (task["reward_pro"], task["reward_usd"], user_id),
        )
        cursor.execute(
            "INSERT INTO transactions (user_id, amount_pro, amount_usd, type, metadata) VALUES (?, ?, ?, ?, ?)",
            (user_id, task["reward_pro"], task["reward_usd"], "offer_reward", str(offer_id)),
        )


def hmac_sha256(secret: bytes, payload: bytes) -> str:
    if not secret:
        return ""
    return hmac.new(secret, payload, digestmod="sha256").hexdigest()


def hmac_sha256_compare(actual: str, expected: str) -> bool:
    if not actual or not expected:
        return False
    return hmac.compare_digest(actual, expected)
