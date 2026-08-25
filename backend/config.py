import os

from dotenv import load_dotenv


load_dotenv()

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))
DIFY_API_URL = os.getenv("DIFY_API_URL", "https://api.dify.ai/v1/chat-messages")
DIFY_TIMEOUT_SECONDS = int(os.getenv("DIFY_TIMEOUT_SECONDS", "60"))


def get_jwt_secret_key() -> str:
    secret_key = os.getenv("JWT_SECRET_KEY")
    if not secret_key:
        raise RuntimeError("JWT_SECRET_KEY environment variable is required")
    return secret_key


def get_dify_api_key() -> str:
    api_key = os.getenv("DIFY_API_KEY")
    if not api_key:
        raise RuntimeError("DIFY_API_KEY environment variable is required")
    return api_key


def get_dify_internal_api_key() -> str:
    api_key = os.getenv("DIFY_INTERNAL_API_KEY")
    if not api_key:
        raise RuntimeError("DIFY_INTERNAL_API_KEY environment variable is required")
    return api_key


def get_agent_api_key() -> str:
    api_key = os.getenv("AGENT_API_KEY")
    if not api_key:
        raise RuntimeError("AGENT_API_KEY environment variable is required")
    return api_key
