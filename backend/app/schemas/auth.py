"""Auth-related Pydantic schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.schemas.limits import Email254, LoginPassword, Password, Str255


class UserBase(BaseModel):
    """Base user schema."""
    email: Email254
    name: Str255


class UserCreate(UserBase):
    """Schema for user signup."""
    password: Password


class UserResponse(UserBase):
    """Schema for user response."""
    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Schema for auth token response."""
    user: UserResponse
    token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    """Schema for login request."""
    email: Email254
    password: LoginPassword


class EventRoleResponse(BaseModel):
    """Schema for event role response."""
    id: UUID
    event_id: UUID
    role: str

    model_config = {"from_attributes": True}


class UserWithRoles(UserResponse):
    """User with their event roles."""
    event_roles: list[EventRoleResponse] = []
