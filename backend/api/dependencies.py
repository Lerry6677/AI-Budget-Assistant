import secrets

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from config import get_agent_api_key, get_dify_internal_api_key
from database import get_db
from services import auth_service


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = auth_service.get_token_user_id(credentials.credentials)
    user = auth_service.get_user_by_id(db, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def verify_dify_internal_key(
    x_dify_internal_key: str | None = Header(default=None),
):
    """Authenticate a server-to-server request made by the Dify HTTP tool."""
    try:
        expected_key = get_dify_internal_api_key()
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dify internal authentication is not configured",
        ) from error

    if not x_dify_internal_key or not secrets.compare_digest(x_dify_internal_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Dify internal key",
        )


def verify_agent_key(
    x_agent_key: str | None = Header(default=None),
):
    """Authenticate a server-to-server request made by an external agent."""
    try:
        expected_key = get_agent_api_key()
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent authentication is not configured",
        ) from error

    if not x_agent_key or not secrets.compare_digest(x_agent_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid agent key",
        )


def get_expense_query_user_id(
    user_id: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    x_dify_internal_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> str:
    """Resolve the target user for either a JWT client or Dify internal call."""
    if x_dify_internal_key is not None:
        verify_dify_internal_key(x_dify_internal_key)
        if not user_id or not user_id.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="user_id is required for Dify internal requests",
            )
        return user_id

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1]
    token_user_id = auth_service.get_token_user_id(token)
    user = auth_service.get_user_by_id(db, token_user_id) if token_user_id is not None else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    current_user_id = str(user.id)
    if user_id is not None and user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot query another user's expenses",
        )
    return current_user_id
