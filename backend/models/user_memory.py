"""结构化长期记忆表。

Task 22 引入。承载"用户偏好 / 稳定事实 / 习惯 / 事件"，
区别于：
    - user_profile     : 硬字段目标（savings_goal / financial_goal）
    - chat_history     : 原始问答对（RAG 召回源）

设计原则：
    - 每条记忆一行（key-value），可独立更新 / 衰减 / 删除。
    - (user_id, key) UNIQUE：去重的核心约束。
    - memory_type 枚举：fact / preference / habit / event。
    - confidence 留给 Task 23 consolidation 用（decay / merge）。
    - source 区分"用户主动声明" / "LLM 抽取" / "系统推断"。
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    Index,
    String,
    UniqueConstraint,
    func,
)

from backend.database import Base


class UserMemory(Base):
    """结构化长期记忆。

    Attributes:
        id:          PK，自增。
        user_id:     用户 ID（与 user_profile.user_id / chat_history.user_id 同型）。
        memory_type: 记忆类型（fact / preference / habit / event）。
        key:         归一化键（lowercase + 去标点 + snake_case），用于去重。
        value:       记忆文本值。
        confidence:  可信度 0~1，Task 23 consolidation 用。
        source:      来源（user_explicit / llm_extracted / system_inferred）。
        created_at:  首次写入时间。
        updated_at:  最后一次更新时间。
    """

    __tablename__ = "user_memory"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_memory_user_id_key"),
        Index("ix_user_memory_user_id_type", "user_id", "memory_type"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    memory_type = Column(String(16), nullable=False)
    key = Column(String(64), nullable=False)
    value = Column(String(512), nullable=False)
    confidence = Column(Float, nullable=False, default=0.5)
    source = Column(String(16), nullable=False, default="llm_extracted")
    created_at = Column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )