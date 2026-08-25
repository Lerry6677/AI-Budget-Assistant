from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import verify_agent_key
from database import get_db
from schemas import AgentExpenseBatch, AgentUserProfileUpdate, ExpenseResponse, UserProfileUpdate
from services import expense_service


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
    return expense_service.get_query_summary(db, user_id, start_time, end_time, category)


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
