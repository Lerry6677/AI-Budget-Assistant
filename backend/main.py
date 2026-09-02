from fastapi import FastAPI

from backend.api import agent_router, chat_router, expense_router, user_router
from backend.database import Base, engine


app = FastAPI(title="AI Budget Assistant API")


@app.on_event("startup")
def create_database_tables():
    """Create missing application tables without changing existing table data."""
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"message": "AI Budget Assistant Running"}


app.include_router(agent_router)
app.include_router(expense_router)
app.include_router(chat_router)
app.include_router(user_router)
