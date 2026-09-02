"""/chat 路由。

根据 config.AGENT_ENABLED 切换：
    - True  : 调用 LangGraph Agent（agent.chat_with_agent）
    - False : 调 Dify（保留旧实现，便于回退）

推荐阅读顺序：先看 _chat_with_agent，再看 _chat_with_dify，最后看 chat 入口。
"""

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
def _chat_with_agent(user_id, message: str) -> str:
    """调用 LangChain Agent：分类→路由→handler→自然语言回复。

    P1 阶段返回的是 (handler_name, reply_text) 元组中的 reply_text。
    L3-2：构造 thread_id = f"user_{user_id}"，让 checkpointer 按用户隔离 state，
          实现多轮对话记忆。第一版固定 1 thread/user，后续可扩多 thread。
    """
    thread_id = f"user_{user_id}"
    _handler, reply = dispatch(user_id=str(user_id), user_input=message, thread_id=thread_id)
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
            answer = _chat_with_agent(user_id, message)
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
