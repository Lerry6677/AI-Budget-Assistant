from pydantic import BaseModel
from typing import List
from datetime import datetime
from typing import Optional

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