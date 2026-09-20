from secrets import compare_digest, token_urlsafe

from fastapi import (
        APIRouter,
        Depends,
        HTTPException,
        Response,
        status
        )

from sqlalchemy import select
from sqlalchemy.exc import Integrity Error

from daemonhunter.auth import (
        CurrentOwner,
        SessionDependency,
        clear_session_cookie,
        hash_password,
        require_owner,
        verify_password,
        )

from daemonhunter.models import User
from daemonhunter.schemas import (
        AdminCreateRequest,
        AdminPasswordresetRequest,
        AdminUpdateRequest,
        OwnerShipTransferRequest,
        UserResponse,
        )


router = APIRouter(
        prefix="/api/v1/admin/users",
        tags=["admin-users"],
        dependencies=[Depends(require_owner)],
        )


def get_user_or_404(
        session: SessionDependency,
        user_id: int,
        ) -> User:

    user = session.get(User, user_id)

    if user is None:
        raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
                )

    return user


def get_secondary_admin_or_403():



def create_admin():
