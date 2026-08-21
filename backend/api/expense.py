from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import ExpenseBatch, ExpenseResponse
from services import expense_service
from api.dependencies import get_current_user


router = APIRouter(tags=["expense"])


@router.post("/expense")
def create_expense(
    data: ExpenseBatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = [expense_service.create_expense(db, expense, str(current_user.id)) for expense in data.expenses]
    return {"success": True, "count": len(results), "data": results}


@router.get("/expense", response_model=List[ExpenseResponse])
def list_expense(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return expense_service.get_expenses(db, str(current_user.id))


@router.delete("/expense/{expense_id}")
def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = expense_service.delete_expense(db, expense_id, str(current_user.id))
    return {"success": deleted}


@router.get("/summary")
def summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return expense_service.get_summary(db, str(current_user.id))


@router.get("/expense/month")
def month_summary(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if month < 1 or month > 12:
        return {"success": False, "message": "month must be between 1 and 12"}
    return expense_service.get_month_summary(db, str(current_user.id), year, month)


@router.get("/expense/query")
def query_expense(
    start_time: datetime,
    end_time: datetime,
    category: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return expense_service.get_query_summary(db, str(current_user.id), start_time, end_time, category)
