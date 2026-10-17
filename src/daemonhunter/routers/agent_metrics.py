from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from daemonhunter.agent_auth import (
        CurrentAgent,
        agent_authentication_error,
        hash_agent_token,
        )
from daemonhunter.auth import SessionDependency, require_ready_admin
from daemonhunter.database import is_sqlite_busy_error
from daemonhunter.models import DeviceAgentCredential, DeviceMetrics
from daemonhunter.routers.admin_devices import get_device_or_404
from daemonhunter.schemas import (
        AgentMetricsRequest,
        AgentTokenResponse,
        DeviceMetricsResponse,
        )


admin_router = APIRouter(
        prefix="/api/v1/admin/devices",
        tags=["admin_agents"],
        dependencies=[Depends(require_ready_admin)],
        )

agent_router = APIRouter(
        prefix="/api/v1/agent",
        tags=["agent"],
        )


@contextmanager
def committed_agent_write(session: Session) -> Iterator[None]:
    try:
        yield
        session.commit()

    except (IntegrityError, StaleDataError) as error:
        session.rollback()

        raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Device or agent registration changed; retry the request",
                ) from error

    except OperationalError as error:
        session.rollback()

        if not is_sqlite_busy_error(error):
            raise

        raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database is busy; retry the request",
                headers={"Retry-After": "1"},
                ) from error

    except Exception:
        session.rollback()
        raise


@admin_router.post(
        "/{device_id}/agent-token",
        response_model=AgentTokenResponse,
        )
def issue_agent_token(
        device_id: int,
        session: SessionDependency,
        ) -> AgentTokenResponse:
    get_device_or_404(session, device_id)

    token = token_urlsafe(32)
    token_hash = hash_agent_token(token)
    issued_at = datetime.now(timezone.utc)

    with committed_agent_write(session):
        result = session.execute(
                update(DeviceAgentCredential)
                .where(deviceAgentCredential.device_id == device_id)
                .values(
                    token_hash=token_hash,
                    issued_at=issued_at,
                    last_used_at=None,
                    )

