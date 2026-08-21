from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Expense, UserProfile
from schemas import ExpenseCreate, UserProfileUpdate
from utils import parse_expense_time


def create_expense(db: Session, expense: ExpenseCreate, user_id: str):
    expense_data = expense.model_dump()
    expense_data["user_id"] = user_id

    if not expense_data.get("expense_time") and expense_data.get("expense_time_text"):
        expense_data["expense_time"] = parse_expense_time(expense_data["expense_time_text"])

    db_expense = Expense(**expense_data)
    db.add(db_expense)
    db.commit()
    db.refresh(db_expense)
    return db_expense


def get_expenses(db: Session, user_id: str):
    return db.query(Expense).filter(Expense.user_id == user_id).all()


def delete_expense(db: Session, expense_id: int, user_id: str):
    expense = db.query(Expense).filter(Expense.id == expense_id, Expense.user_id == user_id).first()
    if expense is None:
        return False

    db.delete(expense)
    db.commit()
    return True


def get_summary(db: Session, user_id: str):
    query = db.query(Expense).filter(Expense.user_id == user_id)
    total_amount = query.with_entities(func.sum(Expense.amount)).scalar()
    expense_count = query.with_entities(func.count(Expense.id)).scalar()
    category_result = query.with_entities(Expense.category, func.sum(Expense.amount)).group_by(Expense.category).all()

    return {
        "total_amount": float(total_amount or 0),
        "expense_count": expense_count,
        "category_summary": {category: float(amount) for category, amount in category_result},
    }


def get_month_summary(db: Session, user_id: str, year: int, month: int):
    start_time = datetime(year, month, 1)
    end_time = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    filters = (
        Expense.user_id == user_id,
        Expense.expense_time >= start_time,
        Expense.expense_time < end_time,
    )

    total_amount = db.query(func.sum(Expense.amount)).filter(*filters).scalar()
    expense_count = db.query(func.count(Expense.id)).filter(*filters).scalar()
    category_result = db.query(Expense.category, func.sum(Expense.amount)).filter(*filters).group_by(Expense.category).all()

    return {
        "total_amount": float(total_amount or 0),
        "expense_count": expense_count or 0,
        "category_summary": {category: float(amount) for category, amount in category_result},
    }


def get_query_summary(db: Session, user_id: str, start_time: datetime, end_time: datetime, category: str | None = None):
    query = db.query(Expense).filter(
        Expense.user_id == user_id,
        Expense.expense_time >= start_time,
        Expense.expense_time < end_time,
    )
    if category:
        query = query.filter(Expense.category == category)

    total_amount = query.with_entities(func.sum(Expense.amount)).scalar()
    expense_count = query.with_entities(func.count(Expense.id)).scalar()
    category_result = query.with_entities(
        Expense.category,
        func.sum(Expense.amount).label("amount"),
        func.count(Expense.id).label("expense_count"),
    ).group_by(Expense.category).order_by(func.sum(Expense.amount).desc()).all()

    category_summary = []
    for category_name, amount, count in category_result:
        percentage = float(amount) / float(total_amount) * 100 if total_amount else 0
        category_summary.append({
            "category": category_name,
            "amount": float(amount),
            "percentage": round(percentage, 2),
            "expense_count": count,
        })

    return {
        "total_amount": float(total_amount or 0),
        "expense_count": expense_count or 0,
        "category_summary": category_summary,
    }


def get_user_profile(db: Session, user_id: str):
    return db.query(UserProfile).filter(UserProfile.user_id == user_id).first()


def update_user_profile(db: Session, user_id: str, profile: UserProfileUpdate):
    db_profile = get_user_profile(db, user_id)
    if db_profile is None:
        db_profile = UserProfile(user_id=user_id)
        db.add(db_profile)

    for field, value in profile.model_dump(exclude_unset=True).items():
        setattr(db_profile, field, value)

    db.commit()
    db.refresh(db_profile)
    return db_profile
