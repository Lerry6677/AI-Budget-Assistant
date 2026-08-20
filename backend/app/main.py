from fastapi import FastAPI
from fastapi import Depends

from sqlalchemy.orm import Session

from typing import List


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