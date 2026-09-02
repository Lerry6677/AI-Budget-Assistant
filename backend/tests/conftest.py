"""pytest 基础设施：独立 SQLite 测试库，不触碰真实 MySQL 数据。

在任何应用模块导入前，将 DATABASE_URL 指向临时 SQLite 文件，
并用测试专用密钥替换 .env 中的 AGENT_API_KEY / JWT_SECRET_KEY，
保证测试与生产环境完全隔离。
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_AGENT_KEY = "test-agent-key-" + uuid.uuid4().hex
TEST_JWT_SECRET = "test-jwt-secret-" + uuid.uuid4().hex
TEST_LLM_API_KEY = "test-llm-api-key-" + uuid.uuid4().hex

# 必须在 config / database 模块导入前设置，避免加载真实 .env 配置
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.gettempdir()) / 'ai_budget_test.sqlite3'}"
os.environ["AGENT_API_KEY"] = TEST_AGENT_KEY
os.environ["JWT_SECRET_KEY"] = TEST_JWT_SECRET
os.environ["LLM_API_KEY"] = TEST_LLM_API_KEY
os.environ["LLM_PROVIDER"] = "openai"
os.environ["LLM_MODEL"] = "gpt-4o-mini"
os.environ["LLM_BASE_URL"] = "https://api.openai.com/v1"

# 阻止 config / database.connection 中的 load_dotenv() 用真实 .env 覆盖测试环境变量
import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False

import pytest
from fastapi.testclient import TestClient

from backend.database import Base, SessionLocal, engine
from backend.main import app
from backend.models import ChatHistory, Expense

# 仅测试生效：SQLite 只对 INTEGER PRIMARY KEY 自增，而 user_profile.id 是 BigInteger；
# 将测试库中的 BIGINT 渲染为 INTEGER，使自增行为与 MySQL 一致，不改动生产模型。
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles


@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture(scope="session", autouse=True)
def _init_test_database():
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
    db_path = Path(engine.url.database)
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def agent_headers():
    return {"X-Agent-Key": TEST_AGENT_KEY}


@pytest.fixture
def user_id():
    return "pytest_user_" + uuid.uuid4().hex[:12]


@pytest.fixture
def other_user_id():
    return "pytest_other_" + uuid.uuid4().hex[:12]


@pytest.fixture(autouse=True)
def _cleanup_test_expenses(user_id, other_user_id):
    yield
    db = SessionLocal()
    try:
        db.query(Expense).filter(
            Expense.user_id.in_([user_id, other_user_id])
        ).delete(synchronize_session=False)
        db.query(ChatHistory).filter(
            ChatHistory.user_id.in_([user_id, other_user_id])
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


@pytest.fixture
def create_expense(client, agent_headers, user_id):
    """返回工厂函数：为测试用户创建一条账单并返回响应中的记录。"""
    def _create(**overrides):
        expense = {
            "category": "餐饮",
            "amount": 25.5,
            "description": "午饭",
            "expense_time": "2026-08-20T12:00:00",
        }
        expense.update(overrides)
        resp = client.post(
            "/agent/expense",
            json={"user_id": user_id, "expenses": [expense]},
            headers=agent_headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["data"][0]

    return _create
