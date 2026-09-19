from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimeSerializer
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
