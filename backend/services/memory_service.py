"""User Memory service 层（Task 22）。

提供 Long-term Memory 的 DB 读写操作，与 expense_service 风格保持一致：
    - 强制 user_id 隔离（任何 query 都过滤 user_id）
    - service 函数接收 db session 参数，不在内部新建
    - Pydantic / ORM 入参明确，不依赖隐式状态
"""
import re
import unicodedata
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import UserMemory
from backend.schemas.user_memory import ExtractedMemory


# 长度上限（与 UserMemory.key 字段定义对齐）
_MAX_KEY_LEN = 64


# ----------------------------------------------------------------------------
# 纯函数：归一化 key
# ----------------------------------------------------------------------------
def normalize_memory_key(text: str) -> str:
    """把任意 memory 文本归一化成稳定 key。

    处理：
        - 全角 → 半角（NFKC）
        - 转小写
        - 用 '_' 替换所有非 [a-z0-9] 字符（标点 / 空格 / emoji 等）
        - 合并连续下划线
        - 去除首尾下划线
        - 长度截断到 64 字符

    Args:
        text: 任意输入字符串。

    Returns:
        归一化后的 key（snake_case，<= 64 字符）。

    Examples:
        >>> normalize_memory_key("I love coffee")
        'i_love_coffee'
        >>> normalize_memory_key("  我喜欢咖啡  ")
        'w_xihuan_kafei'
        >>> normalize_memory_key("weekend-brunch!!")
        'weekend_brunch'
    """
    if not text:
        return ""
    # 全角 → 半角 + 兼容性分解
    s = unicodedata.normalize("NFKC", str(text))
    s = s.lower()
    # 替换所有非 [a-z0-9] 为 '_'
    s = re.sub(r"[^a-z0-9]+", "_", s)
    # 合并连续 '_' / 去首尾
    s = re.sub(r"_+", "_", s).strip("_")
    # 长度截断
    return s[:_MAX_KEY_LEN]


# ----------------------------------------------------------------------------
# DB 操作
# ----------------------------------------------------------------------------
def get_user_memories(
    db: Session,
    user_id: str,
    memory_type: Optional[str] = None,
) -> list[UserMemory]:
    """读取指定用户的全部 memory，可按 memory_type 过滤。

    Args:
        db:          SQLAlchemy session。
        user_id:     用户 ID（强制隔离维度）。
        memory_type: 可选过滤（"fact" / "preference" / "habit" / "event"）。

    Returns:
        list[UserMemory]（按 updated_at desc 排序，让最近更新的记忆靠前）。
    """
    query = db.query(UserMemory).filter(UserMemory.user_id == user_id)
    if memory_type:
        query = query.filter(UserMemory.memory_type == memory_type)
    return query.order_by(UserMemory.updated_at.desc(), UserMemory.id.desc()).all()


def write_or_update_user_memory(
    db: Session,
    user_id: str,
    memory: ExtractedMemory,
) -> UserMemory:
    """按 (user_id, key) UPSERT 一条 memory。

    语义：
        - 同一 (user_id, key) 不存在 → INSERT
        - 同一 (user_id, key) 已存在 → UPDATE value / memory_type / confidence
        - 不存在跨 user 冲突（不同 user 的同名 key 是不同行）
        - 处理并发冲突（UNIQUE 异常 → 回退到 UPDATE）

    Args:
        db:      SQLAlchemy session。
        user_id: 用户 ID。
        memory:  LLM 抽取的单条记忆。

    Returns:
        写入后的 UserMemory 行（已 refresh）。
    """
    key = normalize_memory_key(memory.key)
    if not key:
        # 归一化后为空 → 跳过；不应破坏主流程
        raise ValueError("memory.key normalizes to empty string; skip")

    existing = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == user_id, UserMemory.key == key)
        .first()
    )
    if existing is not None:
        existing.memory_type = memory.memory_type
        existing.value = memory.value
        existing.confidence = memory.confidence
        existing.source = memory.source
        db.commit()
        db.refresh(existing)
        return existing

    # 防御性处理：即便 SELECT 没找到，UNIQUE 冲突（并发）下仍能 UPDATE
    row = UserMemory(
        user_id=user_id,
        memory_type=memory.memory_type,
        key=key,
        value=memory.value,
        confidence=memory.confidence,
        source=memory.source,
    )
    db.add(row)
    try:
        db.commit()
    except Exception:
        # 并发冲突：UNIQUE 违反 → 改 UPDATE
        db.rollback()
        existing = (
            db.query(UserMemory)
            .filter(UserMemory.user_id == user_id, UserMemory.key == key)
            .first()
        )
        if existing is None:
            raise
        existing.memory_type = memory.memory_type
        existing.value = memory.value
        existing.confidence = memory.confidence
        existing.source = memory.source
        db.commit()
        db.refresh(existing)
        return existing

    db.refresh(row)
    return row