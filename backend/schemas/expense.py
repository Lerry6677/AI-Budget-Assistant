from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ExpenseCreate(BaseModel):
    category: str
    amount: float
    description: str
    expense_time: Optional[datetime] = None
    expense_time_text: str | None = None


class ExpenseResponse(ExpenseCreate):
    id: int
    user_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class ExpenseBatch(BaseModel):
    expenses: List[ExpenseCreate]
