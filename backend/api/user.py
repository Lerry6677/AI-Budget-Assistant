from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from models import User
from schemas import LoginRequest, RegisterRequest, TokenResponse, UserProfileResponse, UserProfileUpdate, UserResponse
from services import auth_service, expense_service


router = APIRouter(tags=["user"])


@router.post("/register", response_model=UserResponse, status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    if auth_service.get_user_by_username(db, data.username) is not None:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Username already exists")
    return auth_service.create_user(db, data.username, data.password)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    from fastapi import HTTPException
    user = auth_service.authenticate_user(db, data.username, data.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return {"access_token": auth_service.create_access_token(user), "token_type": "bearer"}


@router.get("/user/profile", response_model=UserProfileResponse)
def get_user_profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user_id = str(current_user.id)
    profile = expense_service.get_user_profile(db, user_id)
    if profile is None:
        return {
            "id": 0,
            "user_id": user_id,
            "savings_goal": None,
            "financial_goal": None,
            "created_at": current_user.created_at,
            "updated_at": current_user.created_at,
        }
    return profile


@router.put("/user/profile", response_model=UserProfileResponse)
def update_user_profile(
    data: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return expense_service.update_user_profile(db, str(current_user.id), data)
