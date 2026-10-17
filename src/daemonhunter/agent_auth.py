import hashlib
import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from daemonhunter.auth import SessionDependency
from daemonhunter.models import DeviceAgentCredential


agent_bearer = HTTPBearer(
        auto_error=False,
        scheme_name="AgentBearer",
        )


@dataclass(frozen=True)
class AgentIdentity:
    device_id: int
    token_hash: str


def hash_agent_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def agent_authentication_error() -> HTTPException:
    return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing agent token",
            headers={"WWW-Authenticate": "Bearer"},
            )


def get_current_agent(
        session: SessionDependency,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(agent_bearer),
            ],
        ) -> AgentIdentity:
    if credentials is None:
        raise agent_authentication_error()

    token = credentials.credentials

    # token_urlsafe(32) produces a 43-character, URL-safe token.
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None:
        raise agent_authentication_error()

    token_hash = hash_agent_token(token)

    credential = session.scalar(
            select(DeviceAgentCredential).where(
                DeviceAgentCredential.token_hash == token_hash,
                )
            )

    if credential is None:
        raise agent_authentication_error()

    return AgentIdentity(
            device_id=credential.device_id,
            token_hash=token_hash,
            )


CurrentAgent = Annotated[
        AgentIdentity,
        Depends(get_current_agent),
        ]
