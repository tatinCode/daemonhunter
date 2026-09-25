from secrets import token_urlsafe

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from daemonhunter.auth import (
        CurrentUser,
        SessionDependency,
        authenticate_user,
        clear_session_cookie,
        hash_password,
        set_session_cookie,
        verify_password,
        )

from daemonhunter.models import User
from daemonhunter.schemas import (
        LoginRequest,
        OwnerSetupRequest,
        PasswordChangeRequest,
        SetupStatusResponse,
        UserResponse,
        )

router = APIRouter(
        prefix="/api/v1/auth",
        tags=["authentication"],
        )

password_hash = PasswordHash.recommend()

# User:
#   id=auto-inc
#   username
#   password_hash
#   session_secret
#   role
#   active


def get_owner(session: SessionDependency) -> User | None:
    statement = select(User).where(User.role == "owner")

    return session.scalar(statement)


@router.get(
        "/setup-status",
        response_model=SetupStatusResponse,
        )
def setup_status(
        session: SessionDependency,
        ) -> SetupStatusResponse:

    return SetupStatusResponse(
            setup_required=get_owner(session) is None,
            )


@router.get(
        "/setup",
        response_model=UserResponse,
        status_code=status.HTTP_201_CREATED,
        )
def setup_owner(
        owner_data: OwnerSetupRequest,
        response: Response,
        session: SessionDependency,
        ) -> User:
    if get_owner(session) is not None:
        raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Owner account already configured",
                )

    owner = User(
            username=owner_data.username,
            password_hash=hash_password(
                owner_data.password.get_secret_value(),
                ),
            session_secret=token_urlsafe(32),
            role="owner",
            active=True,
            must_change_password=False,
            )

    session.add(owner)

    set_session_cookie(response, owner)

    return owner


@router.post(
        "/login",
        response_model=UserResponse,
        )
def login(
        login_data: LoginRequest,
        response: Response,
        session: SessionDependency,
        ) -> User:
    user = authenticate_user(
            session=session,
            username=login_data.username,
            password=login_data.password.get_secret_value(),
            )

    if user is None:
        raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
                )

    set_session_cookie(response, user)

    raise authentication_error()


@router.post(
        "/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        )
def logout(response: Response) -> None:
    clear_session_cookie(response)


@router.get(
        "/me",
        response_model=UserResponse,
        )
def current_user(user: CurrentUser) -> User:
    return user


@router.post(
        "/change-password",
        response_model=UserResponse,
        )
def change_password(
        password_data: PasswordChangeRequest,
        response: Response,
        session: SessionDependency,
        user: CurrentUser,
        ) -> User:

    if not verify_password(
            password_data.current_password.get_secret_value(),
            user.password_hash,
            ):
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
                )

    user.password_hash = hash_password(
            password_data.new_password.get_secret_value,
            )
    user.session_secret = token_urlsafe(32)
    user.must_change_password = False

    session.commit()
    session.refresh(user)
    set_session_cookie(response, user)

    return user
