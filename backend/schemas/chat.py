import re

from typing import Optional

from pydantic import BaseModel, Field, field_validator

# thread_id 白名单字符：仅允许字母数字下划线中划线点冒号，避免被注入其他用户 thread。
# 冒号用于"local:stats" 之类的前缀语义。
_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_.\-:]+$")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # 可选 thread_id：让前端不同页面（"AI 记账" / "统计"）共享同一个用户下
    # 又互不污染对方的对话记忆/历史。缺失时由调用方用 user_id 兜底。
    thread_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value

    @field_validator("thread_id")
    @classmethod
    def thread_id_safe(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not _THREAD_ID_RE.match(value):
            raise ValueError("thread_id contains invalid characters")
        return value


class ChatResponse(BaseModel):
    answer: str
