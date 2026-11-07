from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import database, models
from .config import get_settings

settings = get_settings()
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_context.hash(password)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    return jwt.encode({"sub": subject, "iat": now, "exp": expire}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as local_error:
        if settings.supabase_jwt_secret:
            try:
                return jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
            except jwt.PyJWTError:
                pass
        if settings.supabase_url:
            try:
                client = jwt.PyJWKClient(f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")
                key = client.get_signing_key_from_jwt(token).key
                return jwt.decode(token, key, algorithms=["ES256", "RS256"], audience="authenticated")
            except (jwt.PyJWTError, jwt.PyJWKClientError):
                pass
        raise local_error


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)) -> models.User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="La sesión no es válida o expiró.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        email = payload.get("sub")
        if not isinstance(email, str):
            raise unauthorized
    except jwt.PyJWTError as exc:
        raise unauthorized from exc
    user = db.scalar(select(models.User).where(models.User.email == email.lower()))
    if user is None:
        metadata = payload.get("user_metadata") if isinstance(payload.get("user_metadata"), dict) else {}
        full_name = metadata.get("full_name") or metadata.get("name") or email.split("@", 1)[0]
        user = models.User(
            email=email.lower(),
            full_name=str(full_name)[:160],
            hashed_password=get_password_hash(token_urlsafe(32)),
            role="analyst",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def require_role(*roles: str):
    def dependency(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="No tienes permisos para esta operación.")
        return user
    return dependency
