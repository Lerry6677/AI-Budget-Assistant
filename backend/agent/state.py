"""Agent Graph 的状态定义。

LangGraph 的 Agent 通过一个"状态对象"在节点间传递数据。
对于最常见的"ReAct + 工具调用"场景，状态只需包含：
    - messages: 消息历史（Human / AI / Tool 消息）
    - user_id : 当前会话对应的用户（用于工具内做权限隔离）

L3-1 在此基础上扩展出路由分支所需字段：
    - input              : 用户原始消息
    - intent             : 意图分类结果（"expense" / "chat"）
    - intent_confidence  : LLM 自评置信度（0-1）
    - reply              : 终点回复文本

进阶场景可以再加：
    - plan       : Planner 节点的中间计划
    - retrieved_docs : RAG 检索到的文档
    - profile    : 用户偏好（避免每次都查库）
"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """LangGraph Agent 的状态结构。

    Attributes:
        messages: 消息历史，Annotated + add_messages 让 LangGraph 自动追加而不是覆盖。
        user_id:  当前用户 ID，会被透传到工具的 RunnableConfig 中。
        input:    用户原始消息（API 层传入）。
        intent:   意图分类结果（"expense" / "chat"），由 intent_node 写入。
        intent_confidence: 分类置信度（0-1）。
        reply:    终点回复（由 expense_node / chat_node 写入，API 层读取）。
        thread_id: 当前会话 ID（L3-5：chat_node 写 RAG 历史时用，run_agent 写入）。
    """
    messages: Annotated[list, add_messages]
    user_id: str
    input: str
    intent: str
    intent_confidence: float
    reply: str
    thread_id: str
