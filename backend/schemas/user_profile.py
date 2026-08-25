from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class UserProfileUpdate(BaseModel):
    savings_goal: Optional[float] = None
    financial_goal: Optional[str] = None


class AgentUserProfileUpdate(UserProfileUpdate):
    user_id: int | str


class UserProfileResponse(BaseModel):
    id: int
    user_id: str
    savings_goal: Optional[float] = None
    financial_goal: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
