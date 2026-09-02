"""LangChain / LangGraph Agent 编排层（L3 蓝图）。

对外暴露：
    - run_agent(user_id, user_input, thread_id=None) : 与 Agent 对话，返回最终回复

模块分层：
    - llm.py          LLM 工厂（OpenAI / DashScope / DeepSeek）
    - prompts.py      System Prompt + 3 个抽参 chain（intent / query_params / budget_params）
    - tools.py        LangChain Tool 实现（save / query / analyze / profile）
    - state.py        AgentState（TypedDict，含 thread_id 字段）
    - checkpointer.py 会话记忆持久化（SqliteSaver 单例）
    - rag.py          RAG 检索 + chat_history 持久化（L3-5 单 thread / L3-6 跨 thread）
    - router.py       老 L2 router-based dispatch（L3-1 之后基本不再被 API 调用，保留仅作单元测试 + 兜底）
    - graph.py        5 节点 StateGraph（intent → expense/query/analyze/budget/chat → END）

L3 阶段成果：
    L3-1 5 节点 StateGraph 落地
    L3-2 SqliteSaver checkpointer（thread_id 隔离）
    L3-3 query_tool 端到端
    L3-4 analyze_tool 端到端
    L3-5 budget_tool + TF-IDF RAG 雏形（chat_node 接入）
    L3-6 RAG 升级：跨 thread 检索（embedding 留给后续 P3）
    L3-7 5 节点图结构固化（name="budget_agent_v1"，由 test_l3_7_graph_contract 锁住）
"""

# 延迟导入：避免 import backend.agent 时就把 graph / llm / tools 全部加载，
# 否则 python -m backend.agent.xxx 会触发 RuntimeWarning。
__all__ = ["run_agent"]


def __getattr__(name):
    """PEP 562：模块级 __getattr__，首次访问属性时才真正导入。"""
    if name == "run_agent":
        from .graph import run_agent
        return run_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")