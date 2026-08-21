"""Compatibility exports for the former CRUD module."""

from services.expense_service import (
    create_expense,
    delete_expense,
    get_expenses,
    get_month_summary,
    get_query_summary,
    get_summary,
    get_user_profile,
    update_user_profile,
)

__all__ = [
    "create_expense", "delete_expense", "get_expenses", "get_month_summary", "get_query_summary",
    "get_summary", "get_user_profile", "update_user_profile",
]
