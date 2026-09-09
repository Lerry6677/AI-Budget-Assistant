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

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from sqlalchemy import text  # noqa: E402

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


@app.get("/health")
def health():
    """存活/就绪探针（阶段 3-3）：验证数据库连通，不依赖 Agent / LLM / Dify。

    docker-compose.server.yml 的 backend healthcheck 与服务器监控均打此端点；
    DB 不可达时返回 503，nginx 不会将流量导向未就绪实例。
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 探针需吞掉一切异常转为 503
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}")
    return {"status": "ok"}


app.include_router(agent_router)
app.include_router(expense_router)
app.include_router(chat_router)
app.include_router(user_router)
