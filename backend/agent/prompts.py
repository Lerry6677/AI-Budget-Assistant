"""意图分类 Router。

本模块是 Supervisor 多 Agent 架构的第一步：先把用户消息分到 4 类之一：
    - expense  : 新增或修改/删除账单
    - query    : 查询个人账单
    - analyze  : 统计 / 分析个人账单
    - chat     : 其他所有对话

本文件保持最小化，对外暴露：
    - IntentResult           : Pydantic 结构化结果（category + confidence）
    - IntentCategory         : 4 个枚举值
    - INTENT_CLASSIFIER_PROMPT : 分类用 prompt 模板
    - classify_intent(user_input) : 同步调一次 LLM，返回 IntentResult
"""

from enum import Enum
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from backend.agent.llm import get_llm


class IntentCategory(str, Enum):
    """五类意图。继承 str 是为了能被 LLM 输出直接匹配。"""
    EXPENSE = "expense"
    QUERY = "query"
    ANALYZE = "analyze"
    BUDGET = "budget"
    CHAT = "chat"


class IntentResult(BaseModel):
    """意图分类的结构化输出。

    Attributes:
        category:  5 类意图之一
        confidence: LLM 自评的置信度（0.0-1.0），用于上游决定是否要重试 / 二次确认
        reason:    LLM 给出的简短判断理由，便于排查 bad case
    """
    category: Literal["expense", "query", "analyze", "budget", "chat"] = Field(
        description="意图类别，5 选 1"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="置信度 0-1",
    )
    reason: str = Field(
        default="",
        description="判断理由，简短一句话",
    )


# 单一职责的 prompt：只负责分类
INTENT_CLASSIFIER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "你是意图分类器。把用户消息分到以下4 类之一：\n"
        "  expense  - 新增/修改/删除账单\n"
        "  query    - 查询个人账单\n"
        "  analyze  - 统计/分析个人账单\n"
        "  budget   - 设置/查看储蓄目标或财务目标\n"
        "  chat     - 其他所有对话\n"
        "\n"
        "规则：\n"
        "1) category 必须是 5 个值之一（expense/query/analyze/budget/chat）。\n"
        "2) 涉及用户个人账单数据才能选 query / analyze，否则选 chat。\n"
        "3) confidence 反映你的把握，0.5 以下说明很模糊，建议二次确认。\n"
        "4) reason 用一句话中文写判断理由。\n"
        "5) 输出必须是严格 JSON 对象，字段：category / confidence / reason。\n"
        "   不要使用 Markdown 代码块包裹，不要任何额外解释文字。\n"
        "\n"
        "query 与 analyze 的边界（最容易混淆）：\n"
        "- query  : 用户想要看到具体的数字或记录列表。\n"
        "           关键词：多少、几笔、列出、看看、哪些、有多少、查看。\n"
        "           例：'我今天花了多少钱' '本月餐饮有几条' '最近的账单'\n"
        "- analyze: 用户想要洞察、趋势、占比或建议。\n"
        "           关键词：分析、总结、趋势、占比、为什么、问题、对比、建议。\n"
        "           例：'分析一下我这月消费' '哪个分类占比最高' '和上月对比'\n"
        "- budget : 用户想设置或更新储蓄/财务目标。\n"
        "           关键词：预算、目标、存钱、攒、储蓄、存多少、攒多少、\n"
        "                   财务目标、买房、买车、买XX、计划。\n"
        "           例：'我每月想存 5000' '设置储蓄目标 1 万' '想买新电脑'\n"
        "           注意：用户已经'查询'现存目标时也归 budget。\n"
        "\n"
        "判断捷径：如果用户的问题可以用一个数字直接回答，选 query；\n"
        "         如果需要统计/聚合/解读才回答，选 analyze；\n"
        "         如果用户在说'想要/要'某种目标或金额，选 budget。\n"
    )),
    ("human", "{input}"),
])


class IntentClassificationError(RuntimeError):
    """LLM 返回了无法识别的意图。"""


_intent_chain: Runnable | None = None


def _build_chain() -> Runnable:
    """懒构造分类 chain。"""
    llm = get_llm()
    return (
        INTENT_CLASSIFIER_PROMPT
        | llm.with_structured_output(IntentResult)
    )


def classify_intent(user_input: str) -> IntentResult:
    """调用 LLM 一次性分类，返回 IntentResult（包含 category / confidence / reason）。

    Args:
        user_input: 用户原始消息文本

    Returns:
        IntentResult: 结构化分类结果

    Raises:
        IntentClassificationError: LLM 输出无法解析成 IntentResult
    """
    global _intent_chain
    if _intent_chain is None:
        _intent_chain = _build_chain()

    try:
        return _intent_chain.invoke({"input": user_input})
    except Exception as e:
        raise IntentClassificationError(f"意图分类失败: {e}") from e


if __name__ == "__main__":
    # 直接 python -m backend.agent.prompts 跑测试样例
    samples = [
        "今天午饭花了30元",
        "我今天花了多少钱",
        "分析一下我这个月的消费",
        "你好",
        "日本现在的消费税是多少",
    ]
    for s in samples:
        try:
            r = classify_intent(s)
            print(f"{s!r:40s} → {r.category:8s} | conf={r.confidence:.2f} | {r.reason}")
        except IntentClassificationError as e:
            print(f"{s!r:40s} → ERROR: {e}")


# =============================================================================
# L3-3：Query 参数抽取（自然语言 → {start_date, end_date, category}）
# =============================================================================
class QueryParams(BaseModel):
    """L3-3：从用户 query 消息中抽取的结构化查询条件。

    Attributes:
        start_date: 起始日期（YYYY-MM-DD）。没提到就 None。
        end_date:   结束日期（YYYY-MM-DD）。没提到就 None。
        category:   分类过滤（必须是已知分类之一；没提到就 None）。
    """
    start_date: str | None = Field(
        default=None,
        description="起始日期 YYYY-MM-DD，没提到就 null。",
    )
    end_date: str | None = Field(
        default=None,
        description="结束日期 YYYY-MM-DD，没提到就 null。",
    )
    category: Literal[
        "餐饮", "交通", "购物", "娱乐", "学习", "住房", "医疗", "饮品", "其他"
    ] | None = Field(
        default=None,
        description="分类过滤；没提到分类条件就 null。",
    )


# query 抽参 prompt
QUERY_PARAMS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "你是消费查询参数抽取助手。\n"
        "把用户消息转成 3 个字段：\n"
        "  start_date  - 起始日期 YYYY-MM-DD，例：'今天'→今日，'本月'→本月1号，"
        "'最近7天'→7 天前，'最近30天'→30 天前；没提到日期范围就 null\n"
        "  end_date    - 结束日期 YYYY-MM-DD，例：'今天'→今日，'本月'→今天；"
        "没提到就 null\n"
        "  category    - 分类，必须是以下之一或 null：\n"
        "                餐饮 / 交通 / 购物 / 娱乐 / 学习 / 住房 / 医疗 / 饮品 / 其他\n"
        "\n"
        "今天是 {today}（参考日期）。\n"
        "\n"
        "规则：\n"
        "1) 严格按照今天日期换算相对时间。\n"
        "2) 类别是用户提到的具体分类（如'餐饮''交通'），其他描述（如'吃饭'→餐饮）做合理映射。\n"
        "3) 字段都没提到时全填 null。\n"
        "4) 输出严格 JSON，字段 start_date / end_date / category。\n"
        "   不要 Markdown 代码块，不要任何额外解释。\n"
    )),
    ("human", "{input}"),
])


class QueryParamExtractError(RuntimeError):
    """query 参数抽取失败。"""


_query_params_chain: Runnable | None = None


def _build_query_params_chain() -> Runnable:
    """懒构造 query 抽参 chain。"""
    llm = get_llm()
    return QUERY_PARAMS_PROMPT | llm.with_structured_output(QueryParams)


def classify_query_params(user_input: str) -> QueryParams:
    """从 query 类用户消息中抽取 {start_date, end_date, category}。

    Args:
        user_input: 用户原始消息

    Returns:
        QueryParams

    Raises:
        QueryParamExtractError: LLM 输出解析失败
    """
    global _query_params_chain
    if _query_params_chain is None:
        _query_params_chain = _build_query_params_chain()

    from datetime import date as _date
    today = _date.today().isoformat()
    try:
        return _query_params_chain.invoke({"input": user_input, "today": today})
    except Exception as e:
        raise QueryParamExtractError(f"query 参数抽取失败: {e}") from e


# =============================================================================
# L3-5：Budget 参数抽取（自然语言 → {savings_goal, financial_goal}）
# =============================================================================
class BudgetParams(BaseModel):
    """L3-5：从用户 budget 消息中抽取的结构化目标。

    Attributes:
        savings_goal:   储蓄目标金额（元）。用户没提就 None（不更新）。
        financial_goal: 财务目标描述（自由文本）。用户没提就 None（不更新）。
    """
    savings_goal: float | None = Field(
        default=None,
        description="储蓄目标金额（元，数字），用户没提就 null。",
    )
    financial_goal: str | None = Field(
        default=None,
        description="财务目标描述（自由文本），用户没提就 null。",
    )


BUDGET_PARAMS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "你是预算/目标抽取助手。\n"
        "把用户消息转成 2 个字段：\n"
        "  savings_goal   - 储蓄目标金额（元，浮点数），例：'每月存 5000'→5000，"
        "'攒 1 万'→10000，'我想存钱'→null；用户没明确数字就 null\n"
        "  financial_goal - 财务目标描述（自由文本），例：'买新电脑'→'买新电脑'，"
        "'为买房准备'→'为买房准备'；用户没提就 null\n"
        "\n"
        "规则：\n"
        "1) 字段没提到就 null，**不要为占位填 0 或空串**。\n"
        "2) '省钱''攒钱'这种没数字的，savings_goal 填 null。\n"
        "3) 输出严格 JSON，字段 savings_goal / financial_goal。\n"
        "   不要 Markdown 代码块，不要任何额外解释。\n"
    )),
    ("human", "{input}"),
])


class BudgetParamExtractError(RuntimeError):
    """budget 参数抽取失败。"""


_budget_params_chain: Runnable | None = None


def _build_budget_params_chain() -> Runnable:
    llm = get_llm()
    return BUDGET_PARAMS_PROMPT | llm.with_structured_output(BudgetParams)


def classify_budget_params(user_input: str) -> BudgetParams:
    """从 budget 类用户消息中抽取 {savings_goal, financial_goal}。

    Args:
        user_input: 用户原始消息

    Returns:
        BudgetParams（可能全为 None——表示用户没提具体目标）

    Raises:
        BudgetParamExtractError: LLM 输出解析失败
    """
    global _budget_params_chain
    if _budget_params_chain is None:
        _budget_params_chain = _build_budget_params_chain()
    try:
        return _budget_params_chain.invoke({"input": user_input})
    except Exception as e:
        raise BudgetParamExtractError(f"budget 参数抽取失败: {e}") from e