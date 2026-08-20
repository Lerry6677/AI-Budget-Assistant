from fastapi import FastAPI
from fastapi import Depends

from sqlalchemy.orm import Session

from typing import List
from datetime import datetime

from .database import get_db
from .schemas import ExpenseBatch
from .schemas import ExpenseResponse

from . import crud



app = FastAPI(
    title="AI Budget Assistant API"
)



@app.get("/")
def root():

    return {
        "message":
        "AI Budget Assistant Running"
    }



@app.post("/expense")
def create_expense(
    data: ExpenseBatch,
    db: Session = Depends(get_db)
):

    results = []

    for expense in data.expenses:
        result = crud.create_expense(
            db,
            expense
        )
        results.append(result)

    return {
        "success": True,
        "count": len(results),
        "data": results
    }


@app.get(
    "/expense",
    response_model=List[ExpenseResponse]
)
def list_expense(
        db: Session = Depends(get_db)
):

    return crud.get_expenses(db)


@app.get("/summary")
def summary(
        db: Session = Depends(get_db)
):

    return crud.get_summary(db)

@app.get("/expense/month")
def month_summary(
        user_id: str,
        year: int,
        month: int,
        db: Session = Depends(get_db)
):

    if month < 1 or month > 12:
        return {
            "success": False,
            "message": "month must be between 1 and 12"
        }

    return crud.get_month_summary(
        db,
        user_id,
        year,
        month
    )

@app.get("/expense/query")
def query_expense(
        user_id: str,
        start_time: datetime,
        end_time: datetime,
        category: str | None = None,
        db: Session = Depends(get_db)
):

    return crud.get_query_summary(
        db=db,
        user_id=user_id,
        start_time=start_time,
        end_time=end_time,
        category=category
    )