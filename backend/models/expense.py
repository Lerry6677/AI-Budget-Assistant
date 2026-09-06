from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from backend.database import Base


class Expense(Base):
    __tablename__ = "expense"

    id = Column(Integer, primary_key=True, index=True)
    # user_id 不再保留 ORM default="user001"。
    # DB 实际 schema 已经是 nullable=NO, 这里与 DB 对齐。
    # 应用层必须显式传入 user_id（来自 JWT subject 或 get_current_user）。
    user_id = Column(String(64), nullable=False, index=True)
    category = Column(String(50))
    amount = Column(Float)
    description = Column(String(255))
    expense_time = Column(DateTime, nullable=True)
    expense_time_text = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
