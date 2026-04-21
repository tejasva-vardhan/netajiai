from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from email_service import send_otp_email
from models import OTPCode, User

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)
_auth_secret_warned = False
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_otp_rate_limit_per_minute = 3
_otp_max_attempts = 3


class SendOTPRequest(BaseModel):
    email: EmailStr


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _auth_secret() -> str:
    global _auth_secret_warned
    secret = (os.getenv("AUTH_SECRET_KEY") or "").strip()
    if secret:
        return secret
    if not _auth_secret_warned:
        print("WARNING: AUTH_SECRET_KEY not set; using temporary insecure default for local dev.")
        _auth_secret_warned = True
    return "dev-insecure-auth-secret-change-me"


def _token_ttl_minutes() -> int:
    raw = (os.getenv("AUTH_TOKEN_TTL_MINUTES") or "").strip()
    if raw.isdigit():
        return max(int(raw), 5)
    return 60 * 24 * 7


def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": _now_utc() + timedelta(minutes=_token_ttl_minutes()),
        "typ": "access",
    }
    return jwt.encode(payload, _auth_secret(), algorithm="HS256")


def _verify_access_token(token: str) -> int:
    try:
        payload = jwt.decode(
            token,
            _auth_secret(),
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    sub = payload.get("sub")
    try:
        return int(sub)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token subject") from exc


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    user_id = _verify_access_token(credentials.credentials)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Optional auth dependency:
    - returns User when valid bearer token is present
    - returns None when token missing
    - raises 401 when token is present but invalid
    """
    if not credentials:
        return None
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid auth scheme")
    user_id = _verify_access_token(credentials.credentials)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("/send-otp")
def send_otp(payload: SendOTPRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    now = _now_utc()
    minute_window = now - timedelta(minutes=1)
    recent_count = (
        db.query(OTPCode)
        .filter(
            OTPCode.email == email,
            OTPCode.created_at >= minute_window,
        )
        .count()
    )
    if recent_count >= _otp_rate_limit_per_minute:
        # Generic success-like response to avoid account enumeration and abuse signal leakage.
        return {
            "ok": True,
            "message": "If this email exists, an OTP has been sent.",
        }

    otp = f"{secrets.randbelow(10**6):06d}"
    expires_at = now + timedelta(minutes=10)

    # Keep latest OTP state simple: remove old rows for email, insert a fresh one.
    db.query(OTPCode).filter(OTPCode.email == email).delete()
    db.add(
        OTPCode(
            email=email,
            otp_hash=_pwd_ctx.hash(otp),
            attempts=0,
            created_at=now,
            expires_at=expires_at,
        )
    )
    db.commit()

    try:
        send_otp_email(email, otp)
    except Exception:
        # Do not leak delivery/system details from auth endpoint.
        raise HTTPException(status_code=500, detail="Could not process OTP request.")

    return {
        "ok": True,
        "message": "If this email exists, an OTP has been sent.",
        "expires_in_seconds": 600,
    }


@router.post("/verify-otp")
def verify_otp(payload: VerifyOTPRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    otp = payload.otp.strip()
    if not re.fullmatch(r"\d{6}", otp):
        raise HTTPException(status_code=401, detail="Invalid or expired OTP")

    now = _now_utc()
    rec = (
        db.query(OTPCode)
        .filter(
            OTPCode.email == email,
            OTPCode.expires_at > now,
        )
        .order_by(OTPCode.id.desc())
        .first()
    )
    if not rec:
        raise HTTPException(status_code=401, detail="Invalid or expired OTP")
    if rec.attempts >= _otp_max_attempts:
        db.delete(rec)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired OTP")

    if not rec.otp_hash or not _pwd_ctx.verify(otp, rec.otp_hash):
        rec.attempts = int(rec.attempts or 0) + 1
        if rec.attempts >= _otp_max_attempts:
            db.delete(rec)
        else:
            db.add(rec)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired OTP")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email)
        db.add(user)
        db.flush()

    # Consume OTP codes for this email after successful verification.
    db.query(OTPCode).filter(OTPCode.email == email).delete()
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    return {
        "ok": True,
        "token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
    }
