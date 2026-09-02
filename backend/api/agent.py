from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.dependencies import verify_agent_key
from backend.database import get_db
from backend.schemas import (
    AgentExpenseBatch,
    AgentExpenseUpdate,
    AgentUserProfileUpdate,
    ExpenseResponse,
    ExpenseUpdate,
    UserProfileUpdate,
)
from backend.services import expense_service


router = APIRouter(tags=["agent"])


def _get_agent_query_time_range(
    start_date: date | None,
    end_date: date | None,
) -> tuple[datetime, datetime]:
    start_time = datetime.combine(start_date, time.min) if start_date else datetime(1000, 1, 1)
    end_time = (
        datetime.combine(end_date + timedelta(days=1), time.min)
        if end_date
        else datetime(9999, 12, 31, 23, 59, 59, 999999)
    )

    if end_time <= start_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date must be greater than or equal to start_date",
        )

    return start_time, end_time


@router.get("/agent/test", dependencies=[Depends(verify_agent_key)])
def test_agent_auth():
    return {"message": "agent auth success"}


@router.post("/agent/expense", dependencies=[Depends(verify_agent_key)])
def create_agent_expense(
    data: AgentExpenseBatch,
    db: Session = Depends(get_db),
):
    user_id = str(data.user_id)
    results = [
        expense_service.create_expense(db, expense, user_id)
        for expense in data.expenses
    ]
    return {
        "success": True,
        "count": len(results),
        "data": [ExpenseResponse.model_validate(r) for r in results],
    }


@router.get("/agent/expense/query", dependencies=[Depends(verify_agent_key)])
def query_agent_expense(
    user_id: str = Query(...),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    start_time, end_time = _get_agent_query_time_range(start_date, end_date)
    summary = expense_service.get_query_summary(db, user_id, start_time, end_time, category)
    details = expense_service.get_expenses_in_range(db, user_id, start_time, end_time, category)
    return {
        **summary,
        "details": [ExpenseResponse.model_validate(item) for item in details],
    }


@router.get("/agent/expense/analyze", dependencies=[Depends(verify_agent_key)])
def analyze_agent_expense(
    user_id: str = Query(...),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return combined summary, details and user profile for agent-side analysis."""
    start_time, end_time = _get_agent_query_time_range(start_date, end_date)
    query_summary = expense_service.get_query_summary(db, user_id, start_time, end_time, category)
    details = expense_service.get_expenses_in_range(db, user_id, start_time, end_time, category)
    profile = expense_service.get_user_profile(db, user_id)
    return {
        "user_id": user_id,
        "start_time": start_time,
        "end_time": end_time,
        "query_summary": query_summary,
        "details": [ExpenseResponse.model_validate(item) for item in details],
        "profile": {
            "savings_goal": float(profile.savings_goal) if profile and profile.savings_goal is not None else None,
            "financial_goal": profile.financial_goal if profile else None,
        },
    }


@router.put("/agent/expense/{expense_id}", dependencies=[Depends(verify_agent_key)])
def update_agent_expense(
    expense_id: int,
    data: AgentExpenseUpdate,
    db: Session = Depends(get_db),
):
    user_id = str(data.user_id)
    update_data = ExpenseUpdate(**data.model_dump(exclude={"user_id"}, exclude_unset=True))
    expense = expense_service.update_expense(db, expense_id, user_id, update_data)
    if expense is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found",
        )
    return ExpenseResponse.model_validate(expense)


@router.delete("/agent/expense/{expense_id}", dependencies=[Depends(verify_agent_key)])
def delete_agent_expense(
    expense_id: int,
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    deleted = expense_service.delete_expense(db, expense_id, user_id)
    return {"success": deleted}


@router.get("/agent/profile", dependencies=[Depends(verify_agent_key)])
def get_agent_profile(
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    """Get user profile (memory) for the specified user."""
    profile = expense_service.get_user_profile(db, user_id)
    if profile is None:
        now = datetime.now()
        return {
            "id": 0,
            "user_id": user_id,
            "savings_goal": None,
            "financial_goal": None,
            "created_at": now,
            "updated_at": now,
        }
    return profile


@router.post("/agent/profile", dependencies=[Depends(verify_agent_key)])
def update_agent_profile(
    data: AgentUserProfileUpdate,
    db: Session = Depends(get_db),
):
    """Create or update user profile (memory) for the specified user."""
    user_id = str(data.user_id)
    update_data = UserProfileUpdate(
        **data.model_dump(exclude={"user_id"}, exclude_unset=True)
    )
    return expense_service.update_user_profile(db, user_id, update_data)
