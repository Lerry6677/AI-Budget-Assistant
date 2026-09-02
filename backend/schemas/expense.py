from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ExpenseCreate(BaseModel):
    category: str
    amount: float
    description: str
    expense_time: Optional[datetime] = None
    expense_time_text: str | None = None


class AgentExpenseCreate(ExpenseCreate):
    user_id: int | str


class ExpenseUpdate(BaseModel):
    category: Optional[str] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    expense_time: Optional[datetime] = None
    expense_time_text: Optional[str] = None


class AgentExpenseUpdate(ExpenseUpdate):
    user_id: int | str


class AgentExpenseBatch(BaseModel):
    user_id: int | str
    expenses: List[ExpenseCreate]


class ExpenseResponse(ExpenseCreate):
    id: int
    user_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class ExpenseBatch(BaseModel):
    expenses: List[ExpenseCreate]
