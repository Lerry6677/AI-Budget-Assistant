"""Long-term Memory extraction + 写入的旁路模块（Task 22 Step 3）。

模块职责：
    - 提供 extract_memory_from_chat()：复用 prompts.extract_memory_from_chat
    - 提供 _safe_extract_and_write_memory()：异常全部吞掉，落库失败不影响调用方
    - 提供频控 in-memory dict（每 user 至少 N 条 chat 才触发一次）

设计原则：
    - **不读 RAG / chat_history / user_profile**：避免双调用 / 循环依赖
    - **不修改 AgentState**：所有副作用只走 DB
    - **不修改 graph.py / budget_agent_v1 contract**：本模块是旁路脚本，
      chat_node 接入属于 Step 4，不在本文件范围
"""
import logging
import threading
import time
from typing import Optional

from backend.database import SessionLocal
from backend.schemas.user_memory import ExtractedMemory
from backend.services.memory_service import (
    get_user_memories,
    normalize_memory_key,
    write_or_update_user_memory,
)


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# 频控（防止每条 chat 都触发一次 LLM）
# ----------------------------------------------------------------------------
# in-memory 频控 dict：user_id -> last_extraction_ts
_last_extraction_at: dict[str, float] = {}
_last_extraction_lock = threading.Lock()

# Task 22 默认节流：每 user 至少 30 秒才允许触发一次 extraction
MIN_SECONDS_BETWEEN_EXTRACTION = 30


def _should_extract(user_id: str, now: Optional[float] = None) -> bool:
    """频控判断：同一 user 在 MIN_SECONDS_BETWEEN_EXTRACTION 秒内只允许触发一次。

    Args:
        user_id: 用户 ID。
        now:     当前时间戳（默认 `time.time()`，便于测试注入）。

    Returns:
        True 表示允许触发；False 表示在节流窗口内，跳过。
    """
    if now is None:
        now = time.time()
    with _last_extraction_lock:
        last = _last_extraction_at.get(user_id, 0.0)
        if now - last < MIN_SECONDS_BETWEEN_EXTRACTION:
            return False
        _last_extraction_at[user_id] = now
        return True


def reset_extraction_throttle() -> None:
    """测试用：清空频控 dict。"""
    with _last_extraction_lock:
        _last_extraction_at.clear()


# ----------------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------------
def _safe_extract_and_write_memory(
    user_id: str,
    user_input: str,
    agent_reply: str,
) -> int:
    """旁路异步入口：调 LLM extraction → 写库。

    失败安全：
        - LLM 异常 → logger.warning + return 0（不抛）
        - 单条 write 异常 → logger.warning + continue（不抛）
        - 全程不影响调用方主流程

    Returns:
        实际写入成功的记忆条数（0 表示无信号或全部失败）。
    """
    if not user_id or not user_input:
        logger.debug("user_memory: skip empty user_id / user_input")
        return 0

    if not _should_extract(user_id):
        logger.debug("user_memory: throttled for user=%s", user_id)
        return 0

    # 1) extraction
    try:
        # prompts.extract_memory_from_chat 已在 Step 3 加好
        from backend.agent.prompts import extract_memory_from_chat
        items: list[ExtractedMemory] = extract_memory_from_chat(
            user_input=user_input,
            agent_reply=agent_reply,
        )
    except Exception as e:
        logger.warning("user_memory: extraction failed for user=%s err=%s", user_id, e)
        return 0

    if not items:
        logger.info("user_memory: extraction empty for user=%s", user_id)
        return 0

    # 2) 逐条 UPSERT（每条独立 try/except，单条失败不影响其余）
    written = 0
    db = SessionLocal()
    try:
        for m in items:
            try:
                # 二次过滤：confidence 太低 / key 归一化为空的丢弃
                if m.confidence < 0.3:
                    logger.debug("user_memory: skip low-confidence key=%s conf=%.2f",
                                 m.key, m.confidence)
                    continue
                if not normalize_memory_key(m.key):
                    logger.debug("user_memory: skip empty-normalized key=%r", m.key)
                    continue
                write_or_update_user_memory(db, user_id, m)
                written += 1
            except Exception as e:
                logger.warning("user_memory: write failed key=%s err=%s", m.key, e)
                # 注意：失败时不要 rollback 整体，否则已写入的也被回滚
                db.rollback()
        db.commit()
    except Exception as e:
        logger.warning("user_memory: db session error for user=%s err=%s", user_id, e)
        db.rollback()
    finally:
        db.close()

    logger.info(
        "user_memory: extracted=%d written=%d for user=%s",
        len(items), written, user_id,
    )
    return written


__all__ = [
    "MIN_SECONDS_BETWEEN_EXTRACTION",
    "_safe_extract_and_write_memory",
    "_should_extract",
    "reset_extraction_throttle",
    "get_user_memories",
]