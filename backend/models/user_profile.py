from sqlalchemy import BigInteger, Column, DECIMAL, DateTime, String, func

from backend.database import Base


class UserProfile(Base):
    __tablename__ = "user_profile"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(64), unique=True, nullable=False)
    savings_goal = Column(DECIMAL(10, 2), nullable=True)
    financial_goal = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
