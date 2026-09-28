"""Common Pydantic schemas."""

from typing import Any, Generic, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """Standard error response shape."""
    error: ErrorDetail


class ErrorDetail(BaseModel):
    """Error detail."""
    code: str
    message: str
    details: Optional[dict[str, Any]] = None


class PaginationParams(BaseModel):
    """Pagination query parameters."""
    page: int = 1
    limit: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""
    items: list[T]
    total: int
    page: int
    limit: int
    pages: int
