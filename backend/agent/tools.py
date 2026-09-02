"""Agent 工具集。

每个工具都用 @tool 装饰，把现有的 expense_service / 数据库操作包成 LLM 可调用的函数。
工具的 docstring 会被 LLM 当作"工具描述"，决定何时调用，务必写清楚：
    - 工具做什么
    - 每个参数的含义
    - 何时应该调用 / 不应该调用

【实现建议】
    - 工具内部不直接持有 db session，而是在被调用时通过全局 SessionLocal() 获取
      或者由 graph.py 在 invoke 时把 db 注入到 RunnableConfig
    - 返回值使用 dict（便于 LLM 理解），最终面向用户的文案由 Agent 总结

【与现有 api/agent.py 的关系】
    api/agent.py 里现有 save / query / analyze / profile 的实现逻辑可以直接搬过来，
    包成下面的 @tool 即可。
"""

import os
from datetime import datetime, time, timedelta

from langchain_core.tools import tool
from sqlalchemy.exc import SQLAlchemyError

from backend.database import SessionLocal
from backend.schemas import ExpenseCreate
from backend.services import expense_service


# 调试开关：设 EXPENSE_DRY_RUN=1 时 save_expense 不写库、只回显参数。
# 便于本地无 MySQL 时跑闭环验证。
DRY_RUN = os.getenv("EXPENSE_DRY_RUN", "0") == "1"


# ----------------------------------------------------------------------------
# 工具 1：保存消费（可一次性保存多笔）
# ----------------------------------------------------------------------------
# LLM 拼出的时间字段名是 "time"，但 ExpenseCreate 里叫 "expense_time" / "expense_time_text"
_TIME_KEY_ALIASES = ("time", "expense_time", "expense_time_text")


def _normalize_expense_dict(raw: dict) -> dict:
    """把 LLM 输出的 dict 归一化成 ExpenseCreate 接受的字段。"""
    out = dict(raw)
    # 时间字段归一化
    time_value = None
    for k in _TIME_KEY_ALIASES:
        if k in out:
            time_value = out.pop(k)
            break
    if time_value is not None:
        # ISO 字符串 → datetime；如果是相对时间词（"今天午饭"），留给 service 解析
        if isinstance(time_value, str):
            try:
                out["expense_time"] = datetime.fromisoformat(time_value)
            except ValueError:
                out["expense_time_text"] = time_value
        elif isinstance(time_value, datetime):
            out["expense_time"] = time_value
    return out


@tool
def save_expense(user_id: str, expenses: list[dict]) -> dict:
    """保存一笔或多笔消费记录到数据库。

    调用场景：用户描述了一笔或几笔新消费（例如"今天午饭花了30元""下午奶茶20、晚饭40"）。

    Args:
        user_id:  用户 ID（字符串）。
        expenses: 消费列表，每项应包含：
            - category: 分类，必须是以下之一：
                        餐饮 / 交通 / 购物 / 娱乐 / 学习 / 住房 / 医疗 / 饮品 / 其他
            - amount:   金额，单位"元"，大于 0
            - description: 简短描述（推荐，例如"午饭 - 麦当劳"）
            - time（可选）: 消费时间。ISO 字符串如"2025-09-02T12:30:00"，
                            或自然语言如"今天午饭""昨天""前天"。

    Returns:
        {
            "success": True / False,
            "count":   成功保存的条数,
            "items":   [{"id": ..., "category": ..., "amount": ..., ...}, ...],
            "error":   失败时的错误描述
        }
    """
    if not expenses:
        return {"success": False, "count": 0, "items": [], "error": "expenses 不能为空"}

    # DRY_RUN：只回显参数、不写库
    if DRY_RUN:
        items = []
        for raw in expenses:
            normalized = _normalize_expense_dict(raw)
            items.append({
                "category": normalized.get("category"),
                "amount": normalized.get("amount"),
                "description": normalized.get("description", ""),
            })
        return {"success": True, "count": len(items), "items": items, "dry_run": True}

    db = SessionLocal()
    saved = []
    try:
        for raw in expenses:
            try:
                normalized = _normalize_expense_dict(raw)
                payload = ExpenseCreate(**normalized)
            except Exception as e:
                return {
                    "success": False,
                    "count": len(saved),
                    "items": saved,
                    "error": f"参数解析失败: {e}; raw={raw!r}",
                }
            db_expense = expense_service.create_expense(db, payload, user_id)
            saved.append({
                "id": db_expense.id,
                "category": db_expense.category,
                "amount": db_expense.amount,
                "description": db_expense.description,
            })
        db.commit()
        return {"success": True, "count": len(saved), "items": saved}
    except SQLAlchemyError as e:
        db.rollback()
        return {"success": False, "count": 0, "items": [], "error": f"数据库错误: {e}"}
    finally:
        db.close()


# ----------------------------------------------------------------------------
# 工具 2：查询消费
# ----------------------------------------------------------------------------
def _parse_date(date_str: str | None):
    """YYYY-MM-DD → date；None → None；解析失败 → None（不抛错给 Tool 调用方）。"""
    if not date_str:
        return None
    from datetime import date as _date

    try:
        return _date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def _compute_query_time_range(
    start_date: str | None,
    end_date: str | None,
) -> tuple[datetime, datetime]:
    """仿 api/agent.py::_get_agent_query_time_range。

    L3-3 不引 HTTPException：start_date > end_date 时返回 (now, now) 强制空结果，
    避免 graph 中抛错。
    """
    start_d = _parse_date(start_date)
    end_d = _parse_date(end_date)
    if start_d and end_d and end_d < start_d:
        # 用一个空窗口：start > end
        return datetime(9999, 12, 31), datetime(1, 1, 1)
    start_time = datetime.combine(start_d, time.min) if start_d else datetime(1000, 1, 1)
    end_time = (
        datetime.combine(end_d + timedelta(days=1), time.min)
        if end_d
        else datetime(9999, 12, 31, 23, 59, 59, 999999)
    )
    return start_time, end_time


@tool
def query_expenses(
    user_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
) -> dict:
    """查询用户在指定时间范围内的消费记录。

    调用场景：用户问"今天花了多少""本月餐饮""最近 7 天"等查询类问题。

    Args:
        user_id:    用户 ID
        start_date: 起始日期（YYYY-MM-DD，可选；不传 = 从最早）
        end_date:   结束日期（YYYY-MM-DD，可选；不传 = 至今）
        category:   分类过滤（可选，例：餐饮 / 交通）

    Returns:
        {
            "total":           float，总金额,
            "count":           int，总条数,
            "by_category":     [{category, amount, percentage, expense_count}],
            "details":         [{单条消费的字段...}],
            "start_date":      str,
            "end_date":        str,
            "category_filter": str | None,
            "dry_run":         bool（仅 DRY_RUN 模式下为 True）
        }
    """
    start_time, end_time = _compute_query_time_range(start_date, end_date)

    if DRY_RUN:
        # 不连数据库：返回空结果 + 元数据，验证链路
        return {
            "total": 0.0,
            "count": 0,
            "by_category": [],
            "details": [],
            "start_date": start_date,
            "end_date": end_date,
            "category_filter": category,
            "dry_run": True,
        }

    db = SessionLocal()
    try:
        summary = expense_service.get_query_summary(db, user_id, start_time, end_time, category)
        details = expense_service.get_expenses_in_range(db, user_id, start_time, end_time, category)
        return {
            "total": summary["total_amount"],
            "count": summary["expense_count"],
            "by_category": summary["category_summary"],
            "details": [
                {
                    "id": d.id,
                    "category": d.category,
                    "amount": d.amount,
                    "description": d.description,
                    "expense_time": d.expense_time.isoformat() if d.expense_time else None,
                }
                for d in details
            ],
            "start_date": start_date,
            "end_date": end_date,
            "category_filter": category,
        }
    except SQLAlchemyError as e:
        return {"error": f"数据库错误: {e}", "total": 0, "count": 0, "by_category": [], "details": []}
    finally:
        db.close()


# ----------------------------------------------------------------------------
# 工具 3：消费分析
# ----------------------------------------------------------------------------
@tool
def analyze_expenses(
    user_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """获取用户的消费统计数据（含用户偏好），供 Agent 做进一步分析。

    调用场景：用户问"分析一下我这月消费""对比目标看看""这个月哪些花得最多"等
    需要洞察 / 趋势 / 占比 / 建议的问题。

    与 query_expenses 的区别：
        - analyze 永远聚合全分类（不接受 category 过滤）
        - analyze 额外返回 user profile（savings_goal / financial_goal）
          让 Agent 做"已花 vs 目标"对比
        - analyze 的 summary 是归一化的"category_summary + percentage + count"

    Args:
        user_id:    用户 ID
        start_date: 起始日期（YYYY-MM-DD，可选；不传 = 从最早）
        end_date:   结束日期（YYYY-MM-DD，可选；不传 = 至今）

    Returns:
        {
            "query_summary": {"total_amount", "expense_count", "category_summary": [...]},
            "details":       [{单条消费的字段...}],
            "profile":       {"savings_goal": float|None, "financial_goal": str|None},
            "start_date":    str,
            "end_date":      str,
            "dry_run":       bool
        }
    """
    start_time, end_time = _compute_query_time_range(start_date, end_date)

    if DRY_RUN:
        return {
            "query_summary": {
                "total_amount": 0.0,
                "expense_count": 0,
                "category_summary": [],
            },
            "details": [],
            "profile": {"savings_goal": None, "financial_goal": None},
            "start_date": start_date,
            "end_date": end_date,
            "dry_run": True,
        }

    db = SessionLocal()
    try:
        summary = expense_service.get_query_summary(db, user_id, start_time, end_time)
        details = expense_service.get_expenses_in_range(db, user_id, start_time, end_time)
        profile = expense_service.get_user_profile(db, user_id)
        return {
            "query_summary": summary,
            "details": [
                {
                    "id": d.id,
                    "category": d.category,
                    "amount": d.amount,
                    "description": d.description,
                    "expense_time": d.expense_time.isoformat() if d.expense_time else None,
                }
                for d in details
            ],
            "profile": {
                "savings_goal": float(profile.savings_goal) if profile and profile.savings_goal is not None else None,
                "financial_goal": profile.financial_goal if profile else None,
            },
            "start_date": start_date,
            "end_date": end_date,
        }
    except SQLAlchemyError as e:
        return {
            "error": f"数据库错误: {e}",
            "query_summary": {"total_amount": 0.0, "expense_count": 0, "category_summary": []},
            "details": [],
            "profile": {"savings_goal": None, "financial_goal": None},
        }
    finally:
        db.close()


# ----------------------------------------------------------------------------
# 工具 4：读取/更新用户偏好（长期记忆）
# ----------------------------------------------------------------------------
@tool
def get_user_profile(user_id: str) -> dict:
    """读取用户的偏好与财务目标（savings_goal / financial_goal）。

    调用场景：需要展示用户预算 / 财务目标时，analyze 路径会间接使用。
    L3-5 budget 节点通常只写不读。

    Args:
        user_id: 用户 ID

    Returns:
        {"savings_goal": float | None, "financial_goal": str | None, "dry_run": bool}
    """
    if DRY_RUN:
        return {"savings_goal": None, "financial_goal": None, "dry_run": True}

    db = SessionLocal()
    try:
        profile = expense_service.get_user_profile(db, user_id)
        return {
            "savings_goal": float(profile.savings_goal) if profile and profile.savings_goal is not None else None,
            "financial_goal": profile.financial_goal if profile else None,
        }
    except SQLAlchemyError as e:
        return {"error": f"数据库错误: {e}", "savings_goal": None, "financial_goal": None}
    finally:
        db.close()


@tool
def update_user_profile(
    user_id: str,
    savings_goal: float | None = None,
    financial_goal: str | None = None,
) -> dict:
    """更新用户的偏好与财务目标。

    Args:
        user_id:        用户 ID
        savings_goal:   储蓄目标金额（可选）
        financial_goal: 财务目标描述（可选）

    Returns:
        更新后的 profile
    """
    if DRY_RUN:
        return {
            "savings_goal": savings_goal,
            "financial_goal": financial_goal,
            "dry_run": True,
        }

    db = SessionLocal()
    try:
        from backend.schemas.user_profile import UserProfileUpdate
        update_payload = UserProfileUpdate(
            savings_goal=savings_goal,
            financial_goal=financial_goal,
        )
        profile = expense_service.update_user_profile(
            db,
            user_id,
            update_payload,
        )
        return {
            "savings_goal": float(profile.savings_goal) if profile and profile.savings_goal is not None else None,
            "financial_goal": profile.financial_goal if profile else None,
        }
    except SQLAlchemyError as e:
        return {
            "error": f"数据库错误: {e}",
            "savings_goal": savings_goal,
            "financial_goal": financial_goal,
        }
    finally:
        db.close()


# 导出工具列表（供 graph.py 使用）
ALL_TOOLS = [
    save_expense,
    query_expenses,
    analyze_expenses,
    get_user_profile,
    update_user_profile,
]


__all__ = ["ALL_TOOLS", "save_expense", "DRY_RUN"]
