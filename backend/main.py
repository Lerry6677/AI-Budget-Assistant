import os
import sys

# Allow launching this module as ``uvicorn main:app`` from inside the
# ``backend`` directory by ensuring the ``backend`` package itself is on
# ``sys.path``.
_PKG_PARENT = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_PKG_PARENT)
for _candidate in (_PROJECT_ROOT, _PKG_PARENT):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from backend.api import agent_router, chat_router, expense_router, user_router  # noqa: E402
from backend.database import Base, engine  # noqa: E402


app = FastAPI(title="AI Budget Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
