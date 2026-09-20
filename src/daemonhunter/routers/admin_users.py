from secrets import compare_digest, token_urlsafe

from fastapi import (
        APIRouter,
        Depends,
        HTTPException,
        Response,
        status
        )

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

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
        AdminPasswordResetRequest,
        AdminUpdateRequest,
        OwnershipTransferRequest,
        UserResponse,
        )


router = APIRouter(
        prefix="/api/v1/admin/users",
        tags=["admin-users"],
        dependencies=[Depends(require_owner)],
        )

# User:
#   id=auto-inc
#   username
#   password_hash
#   session_secret
#   role
#   active


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


def get_secondary_admin_or_403(
        session: SessionDependency,
        user_id: int,
        ) -> User:
    user = get_user_or_404(session, user_id)

    if user.role == "owner":
        raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The owner account cannot be modified",
                )

    return user


@router.post(
        "",
        response_model=UserResponse,
        status_code=status.HTTP_201_CREATED,
        )
def create_admin(
        admin_data: AdminCreateRequest,
        session: SessionDependency,
        ) -> User:
    user = User(
            username=admin_data.username,
            password_hash=hash_password(
                admin_data.password_hash.get_secret_value(),
                ),
            session_secret=token_urlsafe(32),
            role="admin",
            active=True,
            must_change_password=True,
            )
    session.add(user)

    try:
        session.commit()

    except IntegrityError as error:
        session.rollback()

        raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this username already exist",
                ) from error

    session.refresh(user)

    return user


@router.get(
        "",
        response_model=list[UserResponse],
        )
def list_users(
        session: SessionDependency,
        ) -> list[User]:
    statement = select(User).order_by(User.id)

    return list(session.scalars(statement))


@router.get(
        "/{user_id}",
        response_model=UserResponse,
        )
def retrieve_user(
        user_id: int,
        session: SessionDependency,
        ) -> User:
    return get_user_or_404(session, user_id)


@router.patch(
        "/{user_id}",
        response_model=UserResponse,
        )
def update_admin(
        user_id: int,
        admin_data: AdminUpdateRequest,
        session: SessionDependency,
        ) -> User:
    user = get_secondary_admin_or_403(session, user_id)
    update_data = admin_data.model_dump(exclude_unset=True)

    if "username" in update_data:
        user.username = update_data["username"]

    if "active" in update_data:
        new_active = update_data["active"]

        if user.active and not new_active:
            user.session_secret = token_urlsafe(32)

        user.active = new_active

    try:
        session.commit

    except IntegrityError as error:
        session.rollback()

        raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this username already exist",
                ) from error

    session.refresh(user)

    return user


@router.post(
        "/{user_id}/reset-password",
        response_model=UserResponse,
        )
def reset_admin_password(
        user_id: int,
        password_data: AdminPasswordResetRequest,
        session: SessionDependency,
        ) -> User:
    user = get_secondary_admin_or_403(session, user_id)

    user.password_hash = hash_password(
            password_data.temporary_password.get_secret_value(),
            )

    user.session_secret = token_urlsafe(32)
    user.must_change_password = True

    session.commit()
    session.refresh(user)

    return user


@router.delete(
        "/{user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        )
def delete_admin(
        user_id: int,
        session: SessionDependency,
        ) -> None:
    user = get_secondary_admin_or_403(session, user_id)

    session.delete(user)
    session.commit()


@router.post(
        "/{user_id}/transfer-ownership",
        status_code=status.HTTP_204_NO_CONTENT,
        )
def transfer_ownership(
        user_id: int,
        transfer_data: OwnershipTransferRequest,
        response: Response,
        session: SessionDependency,
        owner: CurrentOwner,
        ) -> None:
    target = get_secondary_admin_or_403(session, user_id)

    if not target.active:
        raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ownership cannot be transfered to an inactive admin",
                )

    if target.must_change_password:
        raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The target admin must hcnage their temporary password",
                )

    if not compare_digest(
            transfer_data.confirm_username,
            target.username,
            ):
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Confirmation username does not match",
                )

    if not verify_password(
            transfer_data.current_password.get_secrete_value(),
            owner.password_hash,
            ):
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
                )

    owner.role = "admin"
    owner.session_secret = token_urlsafe(32)

# needs to flush the demotion first to satisfy the unique-owner index
    session.flux()

    target.role = "owner"
    target.session_secret = token_urlsafe(32)

    try:
        session.commit()

    except IntegrityError as error:
        session.rollback()

        raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ownership transfer could not be completed",
                ) from error

    clear_session_cookie(response)
