from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from backend.database import Base


class Expense(Base):
    __tablename__ = "expense"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(50), default="user001")
    category = Column(String(50))
    amount = Column(Float)
    description = Column(String(255))
    expense_time = Column(DateTime, nullable=True)
    expense_time_text = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
