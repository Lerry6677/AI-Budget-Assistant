"""Compatibility exports for the former schemas module."""

from backend.schemas import (
    ChatRequest,
    ChatResponse,
    ExpenseBatch,
    ExpenseCreate,
    ExpenseResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserProfileResponse,
    UserProfileUpdate,
    UserResponse,
)

__all__ = [
    "ChatRequest", "ChatResponse", "ExpenseBatch", "ExpenseCreate", "ExpenseResponse",
    "LoginRequest", "RegisterRequest", "TokenResponse", "UserResponse",
    "UserProfileResponse", "UserProfileUpdate",
]
