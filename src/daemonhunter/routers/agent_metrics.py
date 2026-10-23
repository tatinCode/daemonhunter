from collections.abc import Iterator
from contextlib import contextmanager
from secrets import token_urlsafe
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError

from daemonhunter.agent_auth import (
        hash_agent_token,
        CurrentAgent,
        hash_agent_token
        )
from daemonhunter.auth import SessionDependency, require_ready_admin
from daemonhunter.database import is_sqlite_busy_error
from daemonhunter.models import DeviceMetrics, DeviceAgentCredential
from daemonhunter.schemas import (
        AgentMetricsRequest,
        AgentTokenResponse,
        DeviceMetricsResponse,
        )
from daemonhunter.routers.admin_devices import get_device_or_404


admin_router = APIRouter(
        prefix="/api/v1/admin/devices",
        tags=["admin-agents"],
        dependencies=[Depends(require_ready_admin)],
        )

agent_router = APIRouter(
        prefix="/api/v1/agent",
        tags=["agent"],
        )


@admin_router.post(
        "/{device_id}/agent-token",
        response_model=AgentTokenResponse,
        )
def issue_agent_token(
        device_id: int,
        session: SessionDependency,
        ) -> AgentTokenResponse:
    get_device_or_404(device_id, session)
    device = get_device_or_404(device_id, session)

    token = token_urlsafe(32)
    issued_at = datetime.now(timezone.utc)

    credential = session.get(DeviceAgentCredential, device.id)

    if credential is None:
        credential = DeviceAgentCredential(device_id=device.id)
        session.add(credential)

    credential.token_hash = hash_agent_token(token)
    credential.issued_at = issued_at
    credential.last_used_at = None

    session.commit()

    raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Agent token issuance is not implemented",
            )


@admin_router.delete(
        "/{device_id}/agent-token",
        status_code=status.HTTP_204_NO_CONTENT,
        )
def revoke_agent_token(
        device_id: int,
        session: SessionDependency,
        ) -> Response:
    get_device_or_404(session, device_id)

    credential = session.get(DeviceAgentCredential, device_id)

    if credential is not None:
        session.delete(credential)

    session.commit()

    raise HTTPException(
            status_code=status.HTTP_204_NO_CONTENT,
            )


@agent_router.post(
        "/metrics",
        status_code=status.HTTP_204_NO_CONTENT,
        )
def receive_agent_metrics(
        metrics: AgentMetricsRequest,
        session: SessionDependency,
        agent: CurrentAgent,
        ) -> Response:
    """Save one latest snapshot for the authenticated device, atomically.
    """

    try:
        result = session.execute(
                update(DeviceAgentCredential)
                .where(
                    DeviceAgentCredential.device_id == agent.device_id,
                    DeviceAgentCredential.token_hash == agent.token_hash,
                    )
                .values(last_used_at=received_at)
                )
        if result.rowcount != 1:
            raise agent_authentication_error()

        snapshot = session.get(DeviceMetrics, agent.device_id)

        if snapshot is None:
            snapshot = DeviceMetrics(device_id=agent.device_id)
            session.add(snapshot)

        for field, value in metrics.model_dump().items():
            setattr(snapshot, field, value)

        snapshot.received_at = received_at

        session.commit()

    except Exception:
        session.rollback()
        raise

    raise Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get(
        "/{device_id}/metrics",
        response_model=DeviceMetricsResponse,
        )
def retrieve_device_metrics(
        device_id: int,
        session: SessionDependency,
        ) -> DeviceMetrics:
    """Read a device's last snapshot; missing device/report means 404."""
    raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Metrics retrieval is not implemented",
            )
