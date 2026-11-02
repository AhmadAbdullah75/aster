import hashlib
import secrets
import time
from datetime import timedelta
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from .config import settings
from .db import transaction
from .models import RateBucket, Session, User, now

hasher = PasswordHasher()


def allowed_origin(origin: str | None) -> bool:
    if origin == settings.app_origin:
        return True
    # Local development supports both browser spellings without trusting arbitrary
    # hosts, other ports, forwarded headers or origins on deployed installations.
    configured = urlsplit(settings.app_origin)
    if configured.scheme not in {"http", "https"} or configured.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        return False
    port = f":{configured.port}" if configured.port is not None else ""
    return origin in {
        f"{configured.scheme}://{host}{port}" for host in ("localhost", "127.0.0.1", "[::1]")
    }


def digest(token: str) -> str:
    return hashlib.sha256((settings.session_secret + token).encode()).hexdigest()


def limit(key: str, maximum: int, seconds: int = 60):
    window = (int(time.time()) // seconds) * seconds
    with transaction() as db:
        count = db.scalar(
            insert(RateBucket)
            .values(key=key, window=window, count=1)
            .on_conflict_do_update(
                index_elements=["key", "window"], set_={"count": RateBucket.count + 1}
            )
            .returning(RateBucket.count)
        )
        db.execute(delete(RateBucket).where(RateBucket.window < int(time.time()) - 86400))
    if count and count > maximum:
        raise HTTPException(429, "Too many requests. Please wait and try again.")


def verify(password: str, hashed: str) -> bool:
    try:
        return hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def current_user(request: Request) -> User:
    token = request.cookies.get("nexus_session", "")
    with transaction() as db:
        user = db.scalar(
            select(User)
            .join(Session)
            .where(Session.token_hash == digest(token), Session.expires_at > now())
        )
        if not user:
            raise HTTPException(401, "Please sign in.")
        return user


def set_session(response: Response, user_id: str):
    token = secrets.token_urlsafe(48)
    with transaction() as db:
        db.execute(delete(Session).where(Session.expires_at <= now()))
        db.add(
            Session(
                user_id=user_id,
                token_hash=digest(token),
                expires_at=now() + timedelta(days=settings.session_days),
            )
        )
    response.set_cookie(
        "nexus_session",
        token,
        httponly=True,
        secure=settings.cookie_secure
        or settings.app_origin
        not in {"http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://localhost:3000"},
        samesite="lax",
        max_age=settings.session_days * 86400,
        path="/",
    )
