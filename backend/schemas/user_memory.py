"""Long-term Memory Pydantic schemas（Task 22）。

包含：
    - ExtractedMemory / ExtractedMemories  : LLM extraction 输出契约
    - UserMemoryResponse                  : ORM → API 响应序列化
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# Task 22 记忆类型枚举：与 UserMemory.memory_type 字段对齐
MemoryType = Literal["fact", "preference", "habit", "event"]

# Task 22 来源枚举：与 UserMemory.source 字段对齐
MemorySource = Literal["user_explicit", "llm_extracted", "system_inferred"]


class ExtractedMemory(BaseModel):
    """LLM 从对话中抽出的单条记忆。

    Attributes:
        memory_type: 记忆类型（fact / preference / habit / event）。
        key:         归一化 key（snake_case，<= 64 字符）。
        value:       记忆文本值（<= 512 字符）。
        confidence:  可信度 0~1。
        source:      抽取来源。
    """

    memory_type: MemoryType = Field(description="记忆类型")
    key: str = Field(description="归一化 key（snake_case，<= 64 字符）")
    value: str = Field(description="记忆文本值，<= 512 字符")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: MemorySource = Field(default="llm_extracted")


class ExtractedMemories(BaseModel):
    """extraction 可能抽出 0~N 条记忆。"""

    items: list[ExtractedMemory] = Field(default_factory=list)


class UserMemoryResponse(BaseModel):
    """UserMemory ORM 行 → API 响应。"""

    id: int
    user_id: str
    memory_type: str
    key: str
    value: str
    confidence: float
    source: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True