"""ChatHistory ORM（L3-5 新增）。

存储 LangGraph 每个 thread 内 chat_node 完成后的问答对，
供 RAG（TF-IDF 检索）复用。

字段：
    - id: 自增 PK
    - user_id: 用户 ID（强制隔离，必须非空）
    - thread_id: 会话 ID（默认按 user_id 取，run_agent 写入）
    - user_input: 用户原始消息
    - agent_reply: Agent 回复（chat_node 完后由 graph 写入）
    - created_at: 写入时间
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from backend.database import Base


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(50), nullable=False, index=True)
    thread_id = Column(String(100), nullable=False, index=True)
    user_input = Column(Text, nullable=False)
    agent_reply = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
