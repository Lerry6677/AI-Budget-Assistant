from sqlalchemy.orm import Session
from sqlalchemy import func
from .time_parser import parse_expense_time

from .models import Expense
from .schemas import ExpenseCreate
from datetime import datetime


def create_expense(
    db: Session,
    expense: ExpenseCreate
):
    expense_data = expense.model_dump()

    print("原始数据:", expense_data)

    if not expense_data.get("expense_time") and expense_data.get("expense_time_text"):

        text = expense_data["expense_time_text"]

        print("时间文本:", text)

        parsed_time = parse_expense_time(text)

        print("自定义解析结果:", parsed_time)

        expense_data["expense_time"] = parsed_time

    print("最终数据:", expense_data)

    db_expense = Expense(
        **expense_data
    )

    db.add(db_expense)
    db.commit()
    db.refresh(db_expense)

    return db_expense

def get_expenses(
        db: Session
):

    return db.query(
        Expense
    ).all()

def get_summary(
        db: Session
):

    # 总消费金额
    total_amount = db.query(
        func.sum(Expense.amount)
    ).scalar()


    # 消费次数
    expense_count = db.query(
        func.count(Expense.id)
    ).scalar()


    # 分类统计
    category_result = db.query(
        Expense.category,
        func.sum(Expense.amount)
    ).group_by(
        Expense.category
    ).all()


    category_summary = {}

    for category, amount in category_result:

        category_summary[category] = float(amount)


    return {
        "total_amount": float(total_amount or 0),
        "expense_count": expense_count,
        "category_summary": category_summary
    }

def get_month_summary(
    db: Session,
    user_id: str,
    year: int,
    month: int
):
    # 当前月份开始时间
    start_time = datetime(
        year,
        month,
        1
    )

    # 下个月开始时间
    if month == 12:
        end_time = datetime(
            year + 1,
            1,
            1
        )
    else:
        end_time = datetime(
            year,
            month + 1,
            1
        )

    # 基础查询：指定用户 + 指定月份
    base_query = db.query(
        Expense
    ).filter(
        Expense.user_id == user_id,
        Expense.expense_time >= start_time,
        Expense.expense_time < end_time
    )

    # 总消费金额
    total_amount = db.query(
        func.sum(Expense.amount)
    ).filter(
        Expense.user_id == user_id,
        Expense.expense_time >= start_time,
        Expense.expense_time < end_time
    ).scalar()

    # 消费次数
    expense_count = db.query(
        func.count(Expense.id)
    ).filter(
        Expense.user_id == user_id,
        Expense.expense_time >= start_time,
        Expense.expense_time < end_time
    ).scalar()

    # 分类统计
    category_result = db.query(
        Expense.category,
        func.sum(Expense.amount)
    ).filter(
        Expense.user_id == user_id,
        Expense.expense_time >= start_time,
        Expense.expense_time < end_time
    ).group_by(
        Expense.category
    ).all()

    category_summary = {}

    for category, amount in category_result:
        category_summary[category] = float(amount)

    return {
        "total_amount": float(total_amount or 0),
        "expense_count": expense_count or 0,
        "category_summary": category_summary
    }

def get_query_summary(
    db: Session,
    user_id: str,
    start_time: datetime,
    end_time: datetime,
    category: str | None = None
):
    query = db.query(
        Expense
    ).filter(
        Expense.user_id == user_id,
        Expense.expense_time >= start_time,
        Expense.expense_time < end_time
    )

    if category:
        query = query.filter(
            Expense.category == category
        )

    # 总金额
    total_amount = query.with_entities(
        func.sum(Expense.amount)
    ).scalar()

    # 消费笔数
    expense_count = query.with_entities(
        func.count(Expense.id)
    ).scalar()

    # 分类统计
    category_result = query.with_entities(
        Expense.category,
        func.sum(Expense.amount)
    ).group_by(
        Expense.category
    ).all()

    category_summary = {}

    for category_name, amount in category_result:
        category_summary[category_name] = float(amount)

    return {
        "total_amount": float(total_amount or 0),
        "expense_count": expense_count or 0,
        "category_summary": category_summary
    }