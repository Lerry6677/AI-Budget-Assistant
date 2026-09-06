"""Task 23 Step 5：E2E 真实 LLM 验证测试的 conftest。

设计目的：
    - 把"真实调用 LLM API"的测试与"mock 单元测试"完全隔离
    - 不污染 `pytest backend/tests/` 普通测试运行（不引入真实 LLM 调用）
    - 当 LLM_API_KEY 不是真实 key 时，整个 e2e/ 目录全部 SKIPPED（不 FAILED）
    - **不修改 os.environ / sys.modules**：避免影响其他 tests 目录

行为：
    1. 仅在 pytest_collection_modifyitems 中检查 LLM_API_KEY 是否是"真实的"
    2. 只给 e2e/ 子目录下的测试加 skip 标记
    3. 缺 key → 整个 e2e 子目录 skip
    4. 提供 isolation fixture：清空 user_memory + 禁用节流
"""

import os
import uuid
from pathlib import Path

import pytest  # noqa: E402

from backend.agent.memory import reset_extraction_throttle  # noqa: E402
from backend.database import SessionLocal  # noqa: E402
from backend.models import UserMemory  # noqa: E402


# ----------------------------------------------------------------------------
# 真实 key 判定：仅做"是否像真 key"，不修改 os.environ
# ----------------------------------------------------------------------------
# 父 conftest 会设置一个假 key（test-llm-api-key-...），
# 用户可能用 .env 设真 key，也可能完全没设。
# 判定标准：key 不是 test- 前缀、不是占位值、长度 > 20
_PLACEHOLDER_PREFIXES = ("test-llm-api-key", "test-api-key", "replace-with")
_PLACEHOLDER_KEYS = {"", "test-llm-api-key", "replace-with-your-llm-api-key"}


def _has_real_llm_key() -> bool:
    """检查环境是否真的能调用 LLM（不修改 env，只读）。"""
    key = os.environ.get("LLM_API_KEY", "")
    if not key or key in _PLACEHOLDER_KEYS:
        return False
    if any(key.startswith(p) for p in _PLACEHOLDER_PREFIXES):
        return False
    # 真实 key 通常很长（OpenAI sk-... 是 50+ 字符）
    if len(key) < 20:
        return False
    return True


# pytest_collection_modifyitems：在收集阶段给 e2e/ 目录的测试加 skip 标记
def pytest_collection_modifyitems(config, items):
    if _has_real_llm_key():
        return
    skip_marker = pytest.mark.skip(
        reason="LLM_API_KEY 未配置或为占位值，跳过真实 LLM E2E 测试。"
        "设置真实 LLM_API_KEY（长度 > 20，非 test- 前缀）后再运行。"
    )
    e2e_path = str(Path(__file__).resolve().parent).replace("\\", "/")
    for item in items:
        # 只跳过 e2e/ 目录下的测试，不影响普通 tests/
        item_path = str(getattr(item, "fspath", "") or item.location[0])
        if e2e_path in item_path.replace("\\", "/"):
            item.add_marker(skip_marker)


# ----------------------------------------------------------------------------
# 公共 fixtures
# ----------------------------------------------------------------------------
@pytest.fixture
def e2e_user_id():
    """E2E 用用户 ID（区分 pytest_user_ 前缀，方便识别）。"""
    return "e2e_user_" + uuid.uuid4().hex[:12]


@pytest.fixture
def e2e_other_user_id():
    return "e2e_other_" + uuid.uuid4().hex[:12]


@pytest.fixture(autouse=True)
def _e2e_isolation(e2e_user_id, e2e_other_user_id):
    """每个测试前后清理：清空 user_memory + 重置节流 + 重置 LLM chain 单例。

    注意：仅作用于 e2e/ 目录（autouse 在 conftest.py 范围内生效）。
    """
    # 测试前：重置频控 + 清空 LLM extraction chain 单例
    reset_extraction_throttle()
    try:
        from backend.agent import prompts
        prompts._memory_extraction_chain = None
    except Exception:
        pass

    yield

    # 测试后：清理 DB
    db = SessionLocal()
    try:
        db.query(UserMemory).filter(
            UserMemory.user_id.in_([e2e_user_id, e2e_other_user_id])
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


# ----------------------------------------------------------------------------
# 工具：polling 等待 user_memory 出现
# ----------------------------------------------------------------------------
def wait_for_memory(user_id, key=None, timeout=8.0, poll=0.2):
    """polling 等 user_memory 写入完成。

    Args:
        user_id: 用户 ID。
        key:     等待的具体 key（None 表示等任意一条）。
        timeout: 总超时（秒），默认 8s（LLM 调用 + DB 写入通常 < 5s）。
        poll:    轮询间隔（秒）。

    Returns:
        list[UserMemory] 找到的记忆列表；超时返回空列表。
    """
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        db = SessionLocal()
        try:
            q = db.query(UserMemory).filter(UserMemory.user_id == user_id)
            if key is not None:
                q = q.filter(UserMemory.key == key)
            rows = q.all()
            if rows:
                return rows
        finally:
            db.close()
        time.sleep(poll)
    return []


def count_memory(user_id, key=None) -> int:
    """统计 user_memory 行数（精确计数，不轮询）。"""
    db = SessionLocal()
    try:
        q = db.query(UserMemory).filter(UserMemory.user_id == user_id)
        if key is not None:
            q = q.filter(UserMemory.key == key)
        return q.count()
    finally:
        db.close()
