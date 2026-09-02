"""LangGraph StateGraph（L3-1 / L3-2 / L3-3 / L3-4 / L3-5）。

图结构：

START → intent_node
            ↓ (conditional)
            ├─→ expense_node  → save_expense (tool) → END
            ├─→ query_node    → query_expenses (tool) → END     (L3-3)
            ├─→ analyze_node  → analyze_expenses (tool) → END   (L3-4)
            ├─→ budget_node   → update_user_profile (tool) + 写历史 → END   (L3-5)
            └─→ chat_node     → LLM 直答（接 RAG 段落） + 写历史 → END   (L3-5)

业务逻辑全部委托给：
    - prompts.classify_intent / classify_query_params / classify_budget_params
    - tools.save_expense / query_expenses / analyze_expenses / update_user_profile
    - router._summarize / _summarize_query / _summarize_analyze / _summarize_budget
      + _get_extract_chain / _get_chat_chain
    - rag.build_rag_prompt_section (L3-5：chat_node 用)
    - rag.save_chat (L3-5：chat / budget 节点完成后写历史)

node 内部写法：接收 state，返回 dict（增量更新），由 LangGraph 自动 merge 到 state。
"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from backend.agent import rag
from backend.agent.prompts import (
    BudgetParamExtractError,
    IntentCategory,
    IntentClassificationError,
    QueryParamExtractError,
    classify_budget_params,
    classify_intent,
    classify_query_params,
)
from backend.agent.router import (
    _get_chat_chain,
    _get_extract_chain,
    _summarize,
    _summarize_analyze,
    _summarize_budget,
    _summarize_query,
)
from backend.agent.state import AgentState
from backend.agent.tools import (
    analyze_expenses,
    query_expenses,
    save_expense,
    update_user_profile,
)


# ----------------------------------------------------------------------------
# Nodes
# ----------------------------------------------------------------------------
def intent_node(state: AgentState) -> dict:
    """读 state["input"]，调 classify_intent 写入 state["intent"] + state["intent_confidence"]。

    L3-2：同时把 input 推入 state["messages"]，由 add_messages reducer 累积为历史。
    这是图里的"路由器"：返回 dict 决定后续 conditional edge 走向。
    L3-4：expense / query / analyze / chat 都算有效意图，各自走对应节点。
    """
    try:
        result = classify_intent(state["input"])
    except IntentClassificationError as e:
        # 分类失败 → 兜底闲聊，避免 500
        return {
            "intent": "chat",
            "intent_confidence": 0.0,
            "messages": [HumanMessage(content=state["input"])],
            "reply": f"意图分类失败：{e}",
        }

    intent = result.category
    if intent not in (
        IntentCategory.EXPENSE.value,
        IntentCategory.QUERY.value,
        IntentCategory.ANALYZE.value,
        IntentCategory.BUDGET.value,
        IntentCategory.CHAT.value,
    ):
        # 理论上 5 类已穷尽，防御性兜底
        return {
            "intent": intent,
            "intent_confidence": result.confidence,
            "messages": [HumanMessage(content=state["input"])],
            "reply": f"[{intent}] 路由暂未实现（属于 P2/P3 任务）",
        }

    return {
        "intent": intent,
        "intent_confidence": result.confidence,
        "messages": [HumanMessage(content=state["input"])],
    }


def expense_node(state: AgentState) -> dict:
    """处理 expense 意图：LLM 抽取结构化参数 → 调 save_expense 工具 → 翻译回复。

    与 router.handle_expense 等价，只是从函数调用改成 state 读写。
    """
    chain = _get_extract_chain()
    extracted = chain.invoke({"input": state["input"]})

    expenses_payload = [
        {
            "category": it.category,
            "amount": it.amount,
            "description": it.description or state["input"],
            "time": it.time_text,
        }
        for it in extracted.items
    ]

    tool_result = save_expense.invoke({
        "user_id": state["user_id"],
        "expenses": expenses_payload,
    })
    return {"reply": _summarize(tool_result)}


def chat_node(state: AgentState) -> dict:
    """处理 chat 意图：拼 RAG 历史段落 → 调 LLM 闲聊 → 把问答对写 chat_history。

    L3-5：在 L3-1 闲聊基础上接 RAG（单 thread 内）。
    L3-6：默认升级到跨 thread 检索：
        - 当前 thread 的历史已经在 LangGraph messages 里（短期记忆），无需再用 RAG 召回
        - 用 retrieve_similar_cross_thread(..., exclude_thread_id=当前 thread)
          从"同一用户其他会话"里找长期记忆
        - top_k 提到 5，给 LLM 更多上下文

    thread_id 缺失时降级为"无 RAG + 写 anon 历史"，不报错。
    """
    user_id = state["user_id"]
    user_input = state["input"]
    thread_id = state.get("thread_id") or f"anon_{user_id}"

    # 1) 拼 RAG 段落（L3-6：跨 thread，排除当前 thread 防止自召回噪声）
    rag_section = rag.build_rag_prompt_section_cross_thread(
        user_id=user_id,
        query=user_input,
        top_k=5,
        exclude_thread_id=thread_id,
        current_thread_id=thread_id,
    )
    # 2) 调 LLM
    if rag_section:
        sys_text = (
            "你是用户的个人记账助手，可以参考以下**历史会话问答**给出更贴切的回答"
            "（这些来自用户其他会话，不是当前上下文）：\n\n"
            f"{rag_section}"
        )
    else:
        sys_text = "你是 AI Budget Assistant 的闲聊助手。回答简洁友好。"

    result = _get_chat_chain().invoke({
        "input": user_input,
        "system_message": sys_text,
    })

    reply = result.content
    # 3) 持久化
    try:
        rag.save_chat(user_id, thread_id, user_input, reply)
    except Exception:
        # 写历史失败不打断主流程
        pass
    return {"reply": reply}


def query_node(state: AgentState) -> dict:
    """处理 query 意图：LLM 抽 {start_date, end_date, category} → 调 query_expenses → 翻译。

    L3-3：与 router.handle_query 等价，只是从函数调用改成 state 读写。
    失败时（LLM 抽参 / 数据库）写占位 reply，不抛错打断图。
    """
    try:
        params = classify_query_params(state["input"])
    except QueryParamExtractError as e:
        return {"reply": f"查询参数解析失败：{e}"}

    tool_result = query_expenses.invoke({
        "user_id": state["user_id"],
        "start_date": params.start_date,
        "end_date": params.end_date,
        "category": params.category,
    })
    return {"reply": _summarize_query(tool_result)}


def analyze_node(state: AgentState) -> dict:
    """处理 analyze 意图：LLM 抽 {start_date, end_date} → 调 analyze_expenses → 翻译（含 profile）。

    L3-4：与 router.handle_analyze 等价，从函数调用改成 state 读写。
    抽参复用 classify_query_params（与 query_node 同源）。
    失败时（LLM 抽参 / 数据库）写占位 reply，不抛错打断图。
    """
    try:
        params = classify_query_params(state["input"])
    except QueryParamExtractError as e:
        return {"reply": f"分析参数解析失败：{e}"}

    tool_result = analyze_expenses.invoke({
        "user_id": state["user_id"],
        "start_date": params.start_date,
        "end_date": params.end_date,
    })
    return {"reply": _summarize_analyze(tool_result)}


def budget_node(state: AgentState) -> dict:
    """处理 budget 意图：LLM 抽 {savings_goal, financial_goal} → 调 update_user_profile → 翻译。

    L3-5：与 router.handle_budget 等价，从函数调用改成 state 读写。
    抽参失败时写占位 reply，不抛错打断图。
    budget 节点完成后**不写 chat_history**（它属于"目标管理"，不是闲聊）。
    """
    try:
        params = classify_budget_params(state["input"])
    except BudgetParamExtractError as e:
        return {"reply": f"预算参数解析失败：{e}"}

    tool_result = update_user_profile.invoke({
        "user_id": state["user_id"],
        "savings_goal": params.savings_goal,
        "financial_goal": params.financial_goal,
    })
    return {"reply": _summarize_budget(tool_result)}


# ----------------------------------------------------------------------------
# Edge 路由函数
# ----------------------------------------------------------------------------
def _route_after_intent(state: AgentState) -> str:
    """读 state["intent"]，决定下一个节点名。

    返回的字符串必须与 add_conditional_edges 的 path_map key 一致。
    L3-5：5 类意图全部路由到对应节点；其他 → END。
    """
    intent = state.get("intent")
    if intent in ("expense", "query", "analyze", "budget", "chat"):
        return intent
    return END


# ----------------------------------------------------------------------------
# 构造 StateGraph
# ----------------------------------------------------------------------------
def _build_graph(checkpointer=None):
    """懒构造图。模块级单例：第一次调用 compile，后续复用。

    Args:
        checkpointer: LangGraph checkpointer 实例。L3-2 默认挂 SqliteSaver；
                      传 None 则回退到无状态模式（仅用于单元测试）。
    """
    builder = StateGraph(AgentState)

    # 加节点
    builder.add_node("intent_node", intent_node)
    builder.add_node("expense_node", expense_node)
    builder.add_node("query_node", query_node)
    builder.add_node("analyze_node", analyze_node)
    builder.add_node("budget_node", budget_node)
    builder.add_node("chat_node", chat_node)

    # 边：START → intent_node
    builder.add_edge(START, "intent_node")

    # 条件边：intent_node → {expense_node, query_node, analyze_node, budget_node, chat_node, END}
    builder.add_conditional_edges(
        "intent_node",
        _route_after_intent,
        {
            "expense": "expense_node",
            "query": "query_node",
            "analyze": "analyze_node",
            "budget": "budget_node",
            "chat": "chat_node",
            # 防御性兜底
            END: END,
        },
    )

    # 业务节点 → END
    builder.add_edge("expense_node", END)
    builder.add_edge("query_node", END)
    builder.add_edge("analyze_node", END)
    builder.add_edge("budget_node", END)
    builder.add_edge("chat_node", END)

    # L3-7：固化图标识。name 让 LangGraph Studio / API / 测试都能识别"这就是 budget_agent_v1"
    # 防止未来重构时无声息把 5 节点改成 4 或 6 节点（contract 测试会锁住）
    return builder.compile(checkpointer=checkpointer, name="budget_agent_v1")


# 模块级单例
_graph = None
_checkpointer = None


def _get_checkpointer():
    """获取 SqliteSaver 单例（第一版落本地文件，不引 Redis）。

    L3-2 默认 DB 文件：backend/checkpoints.sqlite。
    测试可在 fixture 里 monkeypatch 替换成 MemorySaver。

    注意：SqliteSaver.from_conn_string() 是 @contextmanager，只能在 with 块内用。
    图的 checkpointer 必须在模块生命周期内常驻，所以这里手动构造：
        1. sqlite3.connect(db_path, check_same_thread=False) 拿 conn
        2. SqliteSaver(conn)
    """
    global _checkpointer
    if _checkpointer is None:
        import os
        import sqlite3

        db_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),  # backend/
            "checkpoints.sqlite",
        )
        conn = sqlite3.connect(db_path, check_same_thread=False)
        _checkpointer = SqliteSaver(conn)
    return _checkpointer


def get_graph():
    """获取编译后的图对象（懒构造单例）。挂默认 SqliteSaver。"""
    global _graph
    if _graph is None:
        _graph = _build_graph(checkpointer=_get_checkpointer())
    return _graph


def reset_graph_for_tests():
    """测试用：清空图单例，让下次 get_graph() 重新构造（用于 monkeypatch checkpointer）。"""
    global _graph
    _graph = None


# ----------------------------------------------------------------------------
# 对外入口
# ----------------------------------------------------------------------------
def run_agent(user_id: str, user_input: str, thread_id: str | None = None) -> str:
    """运行图，返回最终回复。

    L3-1 的对外接口，router.dispatch() 会调用这里。
    L3-2 新增 thread_id：
        - 显式传入：checkpointer 按 thread_id 持久化（多轮对话）。
        - 传 None   ：自动生成一次性匿名 thread_id（向后兼容 L3-1 的调用方，
                     老测试不需要关心 thread_id；每次 invoke 都拿到全新 state）。
    L3-2 简化：messages 由 intent_node 负责推入，run_agent 不再预传 HumanMessage，
               这样测试直接 graph.invoke({"input": ...}) 也能累积历史。
    """
    if thread_id is None:
        # 一次性匿名 thread_id：保证 checkpointer 报错分支不被触发
        # （LangGraph 要求有 thread_id 才能配合 checkpointer 使用）
        import uuid
        thread_id = f"anon_{uuid.uuid4().hex}"
    initial_state = {
        "user_id": str(user_id),
        "input": user_input,
        "thread_id": thread_id,  # L3-5：让 chat_node / RAG 拿到当前 thread
    }
    config = {"configurable": {"thread_id": thread_id}}
    final_state = get_graph().invoke(initial_state, config=config)
    return final_state["reply"]


__all__ = [
    "get_graph",
    "run_agent",
    "intent_node",
    "expense_node",
    "query_node",
    "analyze_node",
    "budget_node",
    "chat_node",
    "_route_after_intent",
]