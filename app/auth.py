from typing import Optional
import bcrypt
from fastapi import Request, Response
from itsdangerous import URLSafeSerializer, BadSignature
from .config import settings
from .models import User, get_session

_serializer = URLSafeSerializer(settings.secret_key, salt="rankcraft-session")
COOKIE = "rc_session"


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


def login_user(response: Response, user: User) -> None:
    token = _serializer.dumps({"uid": user.id})
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60*60*24*30)


def logout_user(response: Response) -> None:
    response.delete_cookie(COOKIE)


def current_user(request: Request) -> Optional[User]:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _serializer.loads(raw)
    except BadSignature:
        return None
    uid = data.get("uid")
    if not uid:
        return None
    with get_session() as s:
        return s.get(User, uid)
