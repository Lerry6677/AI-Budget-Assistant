"""路由 + 单意图 handler（P1：expense / query / analyze / budget / chat 五个分支）。

本模块是 Supervisor 多 Agent 架构的最小可行版本：

    user_input
        ↓
    classify_intent(user_input)     # 已有：意图分类
        ↓
    ┌───────────┬───────────────┐
    ↓           ↓               ↓
  expense      query         chat
  (P1)        (后续 P2)       (P1)

P1/L3-3/L3-4/L3-5 实现：
    - handle_expense() : 调 LLM 抽取结构化参数 → 调 save_expense 工具 → 返回
    - handle_query()   : 调 LLM 抽时间/分类参数 → 调 query_expenses 工具 → 翻译回复
    - handle_analyze() : 调 LLM 抽时间参数 → 调 analyze_expenses（含 profile）→ 翻译
    - handle_budget()  : 调 LLM 抽目标参数 → 调 update_user_profile → 翻译回复
    - handle_chat()    : 直接调 LLM 闲聊
    - dispatch()       : 根据 IntentCategory 路由到对应 handler

P2/P3 会把 handle_* 换成 sub-graph，本文件改名 agent/supervisor/graph.py。
"""

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.agent.llm import get_llm
from backend.agent.prompts import IntentCategory, IntentResult, classify_intent
from backend.agent.tools import (
    analyze_expenses,
    query_expenses,
    save_expense,
    update_user_profile,
)


# ----------------------------------------------------------------------------
# expense 专用：从用户消息抽取结构化参数
# ----------------------------------------------------------------------------
class ExtractedExpense(BaseModel):
    """LLM 从用户消息里抽取出的单笔消费结构。"""
    category: Literal["餐饮", "交通", "购物", "娱乐", "学习", "住房", "医疗", "饮品", "其他"] = (
        Field(description="描述")
    )
    amount: float = Field(gt=0, description="金额（元）")
    description: str = Field(default="", description="简短描述")
    time_text: str = Field(default="", description="用户消息中的时间表达原文")


class ExtractedExpenses(BaseModel):
    """LLM 可能抽出一笔或多笔。"""
    items: list[ExtractedExpense] = Field(description="抽取出的消费列表")


_EXTRACT_SYSTEM = (
    "你是消费信息抽取助手。从用户消息里抽取消费记录，输出严格 JSON。\n"
    "\n"
    "分类字典：餐饮 / 交通 / 购物 / 娱乐 / 学习 / 住房 / 医疗 / 饮品 / 其他\n"
    "\n"
    "规则：\n"
    "1) 一条消息可能包含多笔消费（例：'下午奶茶20、晚饭40'），都要抽出来。\n"
    "2) 描述尽量保留原文关键词（例：'午饭 - 麦当劳'）。\n"
    "3) time_text 字段填入用户原文中关于时间的描述（如'今天午饭''昨天晚上'）。\n"
    "4) 输出 JSON，字段：items / category / amount / description / time_text。\n"
    "   不要 Markdown 代码块，不要任何额外解释。\n"
)


_extract_chain = None


def _get_extract_chain():
    """懒构造抽取 chain。"""
    global _extract_chain
    if _extract_chain is None:
        llm = get_llm()
        from langchain_core.prompts import ChatPromptTemplate
        prompt = ChatPromptTemplate.from_messages([
            ("system", _EXTRACT_SYSTEM),
            ("human", "{input}"),
        ])
        _extract_chain = prompt | llm.with_structured_output(ExtractedExpenses)
    return _extract_chain


def _summarize(tool_result: dict) -> str:
    """把 save_expense 的 dict 结果翻译成自然语言回复。"""
    if not tool_result.get("success"):
        return f"记账失败：{tool_result.get('error', '未知错误')}"
    items = tool_result.get("items", [])
    if len(items) == 1:
        it = items[0]
        return f"已记账 {it['category']} {it['amount']} 元（{it['description']}）"
    lines = [f"已记账 {len(items)} 笔："]
    for it in items:
        lines.append(f"  - {it['category']} {it['amount']} 元（{it['description']}）")
    return "\n".join(lines)


def handle_expense(user_id: str, user_input: str) -> str:
    """处理 expense 意图：抽取参数 → 调工具 → 翻译回复。

    Args:
        user_id:   用户 ID
        user_input: 用户原始消息

    Returns:
        自然语言回复字符串
    """
    chain = _get_extract_chain()
    extracted = chain.invoke({"input": user_input})  # ExtractedExpenses

    expenses_payload = []
    for it in extracted.items:
        expenses_payload.append({
            "category": it.category,
            "amount": it.amount,
            "description": it.description or user_input,
            "time": it.time_text,
        })

    tool_result = save_expense.invoke({
        "user_id": user_id,
        "expenses": expenses_payload,
    })
    return _summarize(tool_result)


# ----------------------------------------------------------------------------
# chat 意图：直接调 LLM 闲聊
# ----------------------------------------------------------------------------
_chat_chain = None


def _get_chat_chain():
    """懒构造 chat chain。"""
    global _chat_chain
    if _chat_chain is None:
        from langchain_core.prompts import ChatPromptTemplate
        # system 段支持可选覆盖：传 system_message 时用其内容，
        # 否则用默认闲聊提示。L3-5 RAG 注入靠这个机制。
        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_message}"),
            ("human", "{input}"),
        ])
        _chat_chain = prompt | get_llm()
    return _chat_chain


def _default_chat_system() -> str:
    return "你是 AI Budget Assistant 的闲聊助手。回答简洁友好。"


def handle_chat(user_id: str, user_input: str) -> str:
    """处理 chat 意图：直接 LLM 回答。"""
    result = _get_chat_chain().invoke({
        "input": user_input,
        "system_message": _default_chat_system(),
    })
    return result.content


# ----------------------------------------------------------------------------
# query 意图：抽参 → 调 query_expenses → 翻译回复
# ----------------------------------------------------------------------------
def _summarize_query(tool_result: dict) -> str:
    """把 query_expenses 的 dict 结果翻译成自然语言回复。"""
    if "error" in tool_result:
        return f"查询失败：{tool_result['error']}"
    total = tool_result.get("total", 0)
    count = tool_result.get("count", 0)
    by_cat = tool_result.get("by_category", []) or []
    start = tool_result.get("start_date") or "（无起始）"
    end = tool_result.get("end_date") or "（至今）"
    cat_filter = tool_result.get("category_filter")
    if tool_result.get("dry_run"):
        return (
            f"[DRY_RUN] 收到查询请求：{start} 至 {end}"
            f"{'，分类 ' + cat_filter if cat_filter else ''}。"
            "（未连数据库）"
        )
    if count == 0:
        return f"在 {start} 至 {end} 期间没找到消费记录"
    head = f"在 {start} 至 {end} 共 {count} 笔，总额 {total} 元"
    if cat_filter:
        head += f"（仅 {cat_filter}）"
    if by_cat:
        head += "：\n"
        lines = [f"  - {b['category']} {b['amount']} 元（{b['expense_count']} 笔）" for b in by_cat]
        return head + "\n".join(lines)
    return head + "。"


def handle_query(user_id: str, user_input: str) -> str:
    """处理 query 意图：抽参 → 调 query_expenses → 翻译回复。

    Args:
        user_id:   用户 ID
        user_input: 用户原始消息

    Returns:
        自然语言回复字符串
    """
    from backend.agent.prompts import classify_query_params

    try:
        params = classify_query_params(user_input)
    except Exception as e:
        return f"查询参数解析失败：{e}"

    tool_result = query_expenses.invoke({
        "user_id": user_id,
        "start_date": params.start_date,
        "end_date": params.end_date,
        "category": params.category,
    })
    return _summarize_query(tool_result)


# ----------------------------------------------------------------------------
# analyze 意图：抽时间 → 调 analyze_expenses → 翻译（含目标对比）
# ----------------------------------------------------------------------------
def _summarize_analyze(tool_result: dict) -> str:
    """把 analyze_expenses 的 dict 结果翻译成自然语言。

    L3-4 不做 LLM 二次润色，按固定结构输出：
        1. 区间总览（时间范围 + 笔数 + 总额）
        2. 分类占比（按 amount 降序）
        3. 目标对比（savings_goal / financial_goal）

    空数据 / 错误：返回提示。
    """
    if "error" in tool_result:
        return f"分析失败：{tool_result['error']}"

    summary = tool_result.get("query_summary", {}) or {}
    total = summary.get("total_amount", 0.0)
    count = summary.get("expense_count", 0)
    by_cat = summary.get("category_summary", []) or []
    start = tool_result.get("start_date") or "（无起始）"
    end = tool_result.get("end_date") or "（至今）"
    profile = tool_result.get("profile", {}) or {}

    if tool_result.get("dry_run"):
        return (
            f"[DRY_RUN] 收到分析请求：{start} 至 {end}。"
            "（未连数据库）"
        )
    if count == 0:
        return f"在 {start} 至 {end} 期间无消费记录，无可分析数据"

    lines = [f"📊 {start} 至 {end} 消费分析：", f"共 {count} 笔，总额 {total} 元。"]
    if by_cat:
        lines.append("\n分类占比：")
        for b in by_cat:
            lines.append(
                f"  - {b['category']}：{b['amount']} 元（{b['percentage']:.1f}%，{b['expense_count']} 笔）"
            )

    # 目标对比
    goal_lines = []
    savings_goal = profile.get("savings_goal")
    if savings_goal is not None:
        goal_lines.append(f"  - 储蓄目标 {savings_goal} 元（本月支出 {total} 元）")
    financial_goal = profile.get("financial_goal")
    if financial_goal:
        goal_lines.append(f"  - 财务目标：{financial_goal}")
    if goal_lines:
        lines.append("\n对比目标：")
        lines.extend(goal_lines)
    else:
        lines.append("\n（未设置储蓄/财务目标）")

    return "\n".join(lines)


def handle_analyze(user_id: str, user_input: str) -> str:
    """处理 analyze 意图：抽时间参数 → 调 analyze_expenses → 翻译。

    Args:
        user_id:   用户 ID
        user_input: 用户原始消息

    Returns:
        自然语言回复字符串
    """
    from backend.agent.prompts import classify_query_params

    try:
        params = classify_query_params(user_input)
    except Exception as e:
        return f"分析参数解析失败：{e}"

    tool_result = analyze_expenses.invoke({
        "user_id": user_id,
        "start_date": params.start_date,
        "end_date": params.end_date,
    })
    return _summarize_analyze(tool_result)


# ----------------------------------------------------------------------------
# budget 意图：抽 {savings_goal, financial_goal} → update_user_profile → 翻译
# ----------------------------------------------------------------------------
def _summarize_budget(tool_result: dict) -> str:
    """把 update_user_profile 的结果翻译成自然语言。

    L3-5 不做 LLM 润色，固定结构：
        - DRY_RUN / error：提示
        - 用户提了 savings_goal：显示已设置
        - 用户提了 financial_goal：显示已设置
        - 都没提：友好提示"没识别到目标"
    """
    if "error" in tool_result:
        return f"预算更新失败：{tool_result['error']}"
    if tool_result.get("dry_run"):
        return "[DRY_RUN] 收到预算更新请求（未连数据库）"

    savings = tool_result.get("savings_goal")
    fin = tool_result.get("financial_goal")
    if savings is None and not fin:
        return "未识别到具体目标，请说明储蓄金额或财务目标。"

    lines = ["✅ 已更新您的财务目标："]
    if savings is not None:
        lines.append(f"  - 储蓄目标：{savings} 元/月")
    if fin:
        lines.append(f"  - 财务目标：{fin}")
    lines.append("\n后续分析时会用这些目标做对比。")
    return "\n".join(lines)


def handle_budget(user_id: str, user_input: str) -> str:
    """处理 budget 意图：抽 {savings_goal, financial_goal} → 调 update_user_profile → 翻译。

    Args:
        user_id:   用户 ID
        user_input: 用户原始消息

    Returns:
        自然语言回复字符串
    """
    from backend.agent.prompts import classify_budget_params

    try:
        params = classify_budget_params(user_input)
    except Exception as e:
        return f"预算参数解析失败：{e}"

    tool_result = update_user_profile.invoke({
        "user_id": user_id,
        "savings_goal": params.savings_goal,
        "financial_goal": params.financial_goal,
    })
    return _summarize_budget(tool_result)


# ----------------------------------------------------------------------------
# 路由分发（Supervisor 的最小雏形）
# ----------------------------------------------------------------------------
HandlerName = Literal["expense", "query", "analyze", "chat", "unknown"]


def dispatch(
    user_id: str,
    user_input: str,
    thread_id: str | None = None,
) -> tuple[HandlerName, str]:
    """根据意图分派到对应 handler。

    L3-1 起优先走 LangGraph StateGraph（agent.graph.run_agent）；
    L3-2 起支持 thread_id（多轮对话记忆）。
    图内部仍复用本文件的 _get_extract_chain / _get_chat_chain / _summarize。

    Returns:
        (handler_name, 回复内容)
    """
    from backend.agent.graph import run_agent  # 懒导入避免循环

    try:
        reply = run_agent(user_id, user_input, thread_id=thread_id)
        # run_agent 只返回 reply，不返回 intent。
        # 按回复前缀推断 handler name（_summarize 的契约："已记账 ..."）。
        if reply.startswith("已记账"):
            return ("expense", reply)
        return ("chat", reply)
    except Exception as e:
        # 终极降级：直接走原来的 if/else 逻辑（不带 checkpointer）
        try:
            result: IntentResult = classify_intent(user_input)
        except Exception as ee:
            return ("unknown", f"意图分类失败：{ee}")
        category = result.category
        if category == IntentCategory.EXPENSE.value:
            return ("expense", handle_expense(user_id, user_input))
        if category == IntentCategory.QUERY.value:
            return ("query", handle_query(user_id, user_input))
        if category == IntentCategory.ANALYZE.value:
            return ("analyze", handle_analyze(user_id, user_input))
        if category == IntentCategory.BUDGET.value:
            return ("budget", handle_budget(user_id, user_input))
        if category == IntentCategory.CHAT.value:
            return ("chat", handle_chat(user_id, user_input))
        return (category, f"[{category}] 路由暂未实现（属于 P2/P3 任务）")


__all__ = [
    "dispatch",
    "handle_expense",
    "handle_query",
    "handle_analyze",
    "handle_budget",
    "handle_chat",
]