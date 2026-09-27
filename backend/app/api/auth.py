"""Authentication API routes."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.services.auth_service import create_user, authenticate_user, generate_token, get_user_roles
from app.schemas.auth import (
    UserCreate,
    LoginRequest,
    TokenResponse,
    UserResponse,
    UserWithRoles,
    EventRoleResponse,
)
from app.models.user import User
from app.schemas.api import MessageOut
from app.config import settings
from app.utils.fingerprint import client_ip
from app.utils.rate_limit import hit, peek

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    user_data: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user account (rate limited per IP)."""
    ok, retry = await hit(f"signup:{client_ip(request)}", settings.RATE_LIMIT_SIGNUPS_PER_MINUTE, 60)
    if not ok:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many sign-ups from this address, slow down",
                            headers={"Retry-After": str(retry)})
    try:
        user = await create_user(
            db=db,
            email=user_data.email,
            password=user_data.password,
            name=user_data.name,
        )
        token = generate_token(user)
        return TokenResponse(
            user=UserResponse.model_validate(user),
            token=token,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and return JWT token. Repeated *failures* are throttled (429); successes never are."""
    ip, email = client_ip(request), credentials.email.lower()
    keys = ((f"loginfail:{ip}:{email}", settings.LOGIN_MAX_FAILURES), (f"loginfail:ip:{ip}", settings.LOGIN_MAX_FAILURES_PER_IP))
    for key, cap in keys:
        blocked, retry = await peek(key, cap, 300)
        if blocked:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail="Too many failed sign-in attempts. Try again later.",
                                headers={"Retry-After": str(retry)})
    try:
        user = await authenticate_user(
            db=db,
            email=credentials.email,
            password=credentials.password,
        )
    except ValueError as e:
        for key, cap in keys:
            await hit(key, cap, 300)  # record the failure
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    token = generate_token(user)
    return TokenResponse(
        user=UserResponse.model_validate(user),
        token=token,
    )


@router.post("/logout", response_model=MessageOut)
async def logout(
    current_user: User = Depends(get_current_user),
):
    """Logout (client should discard token)."""
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserWithRoles)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user with their event roles."""
    roles = await get_user_roles(db, current_user.id)
    return UserWithRoles(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        created_at=current_user.created_at,
        event_roles=[
            EventRoleResponse(
                id=r.id,
                event_id=r.event_id,
                role=r.role.value,
            )
            for r in roles
        ],
    )
