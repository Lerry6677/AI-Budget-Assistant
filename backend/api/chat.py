from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_current_user
from models import User
from schemas import ChatRequest, ChatResponse
from services.dify_service import DifyServiceError, chat_with_dify


router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(data: ChatRequest, current_user: User = Depends(get_current_user)):
    try:
        answer = chat_with_dify(user_id=current_user.id, message=data.message)
    except (DifyServiceError, RuntimeError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service is temporarily unavailable",
        ) from error

    return {"answer": answer}
