"""/chat 路由。

根据 config.AGENT_ENABLED 切换：
    - True  : 调用 LangGraph Agent（agent.chat_with_agent）
    - False : 调 Dify（保留旧实现，便于回退）

推荐阅读顺序：先看 _chat_with_agent，再看 _chat_with_dify，最后看 chat 入口。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from backend.agent.router import dispatch
from backend.api.dependencies import get_current_user
from backend.config import AGENT_ENABLED
from backend.models import User
from backend.schemas import ChatRequest, ChatResponse
from backend.services.dify_service import DifyServiceError, chat_with_dify


router = APIRouter(tags=["chat"])


# ----------------------------------------------------------------------------
# LangGraph Agent 路径
# ----------------------------------------------------------------------------
def _chat_with_agent(user_id, message: str, thread_id: str | None = None) -> str:
    """调用 LangChain Agent：分类→路由→handler→自然语言回复。

    P1 阶段返回的是 (handler_name, reply_text) 元组中的 reply_text。
    L3-2：thread_id 默认 f"user_{user_id}"，让 checkpointer 按用户隔离 state。
          支持传入 thread_id 以隔离不同页面（如"AI 记账" vs "统计"）。
    """
    tid = thread_id or f"user_{user_id}"
    _handler, reply = dispatch(user_id=str(user_id), user_input=message, thread_id=tid)
    return reply


# ----------------------------------------------------------------------------
# Dify 路径（兼容旧实现）
# ----------------------------------------------------------------------------
def _chat_with_dify(user_id, message: str) -> str:
    """调用 Dify 获取回答。"""
    return chat_with_dify(user_id=user_id, message=message)


# ----------------------------------------------------------------------------
# 路由入口
# ----------------------------------------------------------------------------
@router.post("/chat", response_model=ChatResponse)
def chat(data: ChatRequest, current_user: User = Depends(get_current_user)):
    """统一聊天入口，根据 AGENT_ENABLED 走不同实现。"""
    user_id = current_user.id
    message = data.message

    try:
        if AGENT_ENABLED:
            answer = _chat_with_agent(user_id, message, thread_id=data.thread_id)
        else:
            answer = _chat_with_dify(user_id, message)
    except NotImplementedError as error:
        # Agent 还没接好时给出明确提示，避免 500 看不出原因
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Agent path is enabled but not implemented yet. "
                "Complete backend/agent/ first, or set AGENT_ENABLED=false to use Dify."
            ),
        ) from error
    except DifyServiceError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service is temporarily unavailable",
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error) or "AI service is temporarily unavailable",
        ) from error

    return {"answer": answer}


@router.get("/chat/history", response_model=List[dict])
def get_chat_history(
    limit: int = 50,
    thread_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """拉取当前用户的闲聊历史问答对（按时间升序，用户-助手交错）。

    说明：
        只覆盖"闲聊"意图（chat_node 完后由 graph 写入）。
        expense / query / analyze / budget 等节点的对话不会出现在这里。
        thread_id 不传时返回默认 thread（f"user_{user_id}"）下的所有历史；
        传入具体 thread_id 则只返回该会话的历史（用于"AI 记账" vs "统计" 隔离）。
    """
    import re as _re

    from backend.database import SessionLocal
    from backend.models import ChatHistory

    if thread_id is not None and not _re.match(r"^[A-Za-z0-9_.\-:]+$", thread_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="thread_id contains invalid characters",
        )

    user_id = str(current_user.id)
    db = SessionLocal()
    try:
        query = db.query(ChatHistory).filter(ChatHistory.user_id == user_id)
        if thread_id is not None:
            query = query.filter(ChatHistory.thread_id == thread_id)
        rows = (
            query.order_by(ChatHistory.created_at.asc())
            .limit(limit)
            .all()
        )
        messages: list[dict] = []
        for row in rows:
            messages.append(
                {
                    "id": f"{row.id}-user",
                    "role": "user",
                    "content": row.user_input,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
            messages.append(
                {
                    "id": f"{row.id}-ai",
                    "role": "ai",
                    "content": row.agent_reply,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return messages
    finally:
        db.close()
