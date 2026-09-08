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
# thread_id 用户级隔离（阶段 2-1）
# ----------------------------------------------------------------------------
# 前端未显式指定会话空间时使用的默认标识。
DEFAULT_CONVERSATION_ID = "main"

# graph._persist_history 依赖 "local:" 前缀跳过 chat_history 落库（"前端 only"
# 模式，如"统计"页）。该前缀必须留在 scoped thread_id 的最前面，否则契约被破坏。
LOCAL_THREAD_PREFIX = "local:"


def build_scoped_thread_id(user_id, conversation_id: str | None = None) -> str:
    """把前端传来的"会话空间名"绑定到 JWT 验证过的用户上，生成隔离的 thread_id。

    为什么必须做这件事：
        thread_id 是 LangGraph checkpointer 的唯一分区键
        （run_agent 里 config={"configurable": {"thread_id": ...}}），而
        AgentState.messages 是 add_messages 累加型字段。前端 Chat 页硬编码
        thread_id="main"、统计页硬编码 "local:stats"，若原样透传，所有用户就共用
        同一个 checkpoint 线程 —— chat_node 拼给 LLM 的 history 里会混入别人的对话。

    规则：
        - user_id 一律取自 JWT（current_user.id），绝不采信请求体/查询串里的 user_id
        - conversation_id 缺省或空白时用 DEFAULT_CONVERSATION_ID
        - 普通会话：      f"{user_id}:{conversation_id}"    例 "26:main"
        - "local:" 会话： f"local:{user_id}:{rest}"         例 "local:26:stats"
          （用户段插在 "local:" 之后，保持 _persist_history 的跳过契约不变）

    由此保证：同一个 conversation_id 在不同用户下必然得到不同 thread_id。
    """
    uid = str(user_id)
    conv = (conversation_id or "").strip() or DEFAULT_CONVERSATION_ID
    if conv.startswith(LOCAL_THREAD_PREFIX):
        rest = conv[len(LOCAL_THREAD_PREFIX):].strip() or DEFAULT_CONVERSATION_ID
        return f"{LOCAL_THREAD_PREFIX}{uid}:{rest}"
    return f"{uid}:{conv}"


# ----------------------------------------------------------------------------
# LangGraph Agent 路径
# ----------------------------------------------------------------------------
def _chat_with_agent(user_id, message: str, thread_id: str | None = None) -> str:
    """调用 LangChain Agent：分类→路由→handler→自然语言回复。

    P1 阶段返回的是 (handler_name, reply_text) 元组中的 reply_text。
    阶段 2-1：thread_id 一律经 build_scoped_thread_id 绑定到 JWT 用户后再交给
              checkpointer。前端传来的值只作为"会话空间名"（区分"AI 记账" vs
              "统计"），不再直接充当跨用户共享的 checkpoint 分区键。
    """
    tid = build_scoped_thread_id(user_id, thread_id)
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
        thread_id 不传时返回该用户名下所有会话的历史；
        传入具体 thread_id 则只返回该会话的历史（用于"AI 记账" vs "统计" 隔离）。

    阶段 2-1：传入的 thread_id 先经 build_scoped_thread_id 绑定到 JWT 用户，与
              /chat 的写入端保持同一套规则；即便前端伪造别人的会话名，也会被
              scope 进自己的命名空间，叠加下面的 user_id 过滤形成双重隔离。
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
    # 与 /chat 写入端同规则：把前端传来的会话名 scope 到当前 JWT 用户。
    scoped_thread_id = (
        build_scoped_thread_id(user_id, thread_id) if thread_id is not None else None
    )
    db = SessionLocal()
    try:
        query = db.query(ChatHistory).filter(ChatHistory.user_id == user_id)
        if scoped_thread_id is not None:
            query = query.filter(ChatHistory.thread_id == scoped_thread_id)
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
