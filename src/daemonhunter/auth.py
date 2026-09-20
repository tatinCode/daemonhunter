from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from daemonhunter.config import COOKIE_SECURE
from daemonhunter.database import get_session
from daemonhunter.models import User


COOKIE_NAME = "daemonhunter_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 14
SESSION_SALT = "daemonhunter-session"

password_hash = PasswordHash.recommend()
dummy_password_hash = password_hash.hash("not-a-real-password")

SessionDependency = Annotated[Session, Depends(get_session)]


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(
        password: str,
        stored_hash: str,
        ) -> bool:
    return password_hash.verify(password, stored_hash)


def authenticate_user(
        session: Session,
        username: str,
        password: str
        ) -> User | None:
    statement = select(User).where(User.username == username)

    user = session.scalar(statement)

    stored_hash = (
            user.password_hash
            if user is not None
            else dummy_password_hash
            )

    valid_password = verify_password(password, stored_hash)
    valid_username = (
            user is not None
            and compare_digest(username, user.username)
            )

    if (
            not valid_username
            or not valid_password
            or user is None
            or not user.active
            ):
        return None

    return user


def create_session_token(user: User) -> str:
    serializer = URLSafeTimedSerializer(
            secret_key=user.session_secret,
            salt=SESSION_SALT,
            )

    signed_token = serializer.dumps({"user_id": user.id})

    return f"{user.id}.{signed_token}"


def set_session_cookie(
        response: Response,
        user: User,
        ) -> None:
    response.set_cookie(
            key=COOKIE_NAME,
            value=create_session_token(user),
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            secure=COOKIE_SECURE,
            samesite="lax",
            path="/",
            )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
            key=COOKIE_NAME,
            httponly=True,
            secure=COOKIE_SECURE,
            samesite="lax",
            path="/",
            )


def authentication_error() -> HTTPException:
    return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication Required",
            )


def get_current_user(
        request: Request,
        session: SessionDependency,
        ) -> User:
    cookie = request.cookies.get(COOKIE_NAME)

    if cookie is None:
        return authentication_error()

    try:
        user_id_text, signed_token = cookie.split(".", maxsplit=1)
        user_id = int(user_id_text)

    except (TypeError, ValueError):
        raise authentication_error() from None

    if user_id < 1:
        raise authentication_error()

    user = session.get(User, user_id)

    if user is None or not user.active:
        raise authentication_error()

    serializer = URLSafeTimedSerializer(
            secret_key=user.session_secret,
            salt=SESSION_SALT,
            )

    try:
        payload = serializer.loads(
                signed_token,
                max_age=COOKIE_MAX_AGE,
                )

    except BadSignature as error:
        raise authentication_error() from error

    if (
            not isinstance(payload, dict)
            or payload.get("user_id") != user.id
            ):
        raise authentication_error()

    return user


CurrentUser = Annotated[
        User,
        Depends(get_current_user),
        ]


def require_ready_admin(user: CurrentUser) -> User:
    if user.must_change_password:
        raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password change required",
                )

    return user


ReadyAdmin = Annotated[
        User,
        Depends(require_ready_admin)
        ]


def require_owner(user: ReadyAdmin) -> User:
    if user.role != "owner":
        raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Owner acces required",
                )

    return user


CurrentOwner = Annotated[
        User,
        Depends(require_owner),
        ]
