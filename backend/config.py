"""Application configuration loaded from environment variables.

集中管理：
- 数据库 / JWT 鉴权
- LLM 接入参数（LangChain Agent 使用）
- Dify 兼容配置（仅在 AGENT_ENABLED=false 时使用）
"""

import os

from dotenv import load_dotenv


load_dotenv()


# ----------------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------------
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))


def get_jwt_secret_key() -> str:
    secret_key = os.getenv("JWT_SECRET_KEY")
    if not secret_key:
        raise RuntimeError("JWT_SECRET_KEY environment variable is required")
    return secret_key


# ----------------------------------------------------------------------------
# Agent 开关
# ----------------------------------------------------------------------------
# True  -> /chat 走 LangChain Agent（推荐）
# False -> /chat 继续走 Dify（兼容）
AGENT_ENABLED = os.getenv("AGENT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


# ----------------------------------------------------------------------------
# LLM 配置（LangChain Agent 使用）
# ----------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
LLM_MODEL = os.getenv("LLM_MODEL", "MiniMaxAI/MiniMax-M3")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.gmi-serving.com/v1")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))


def get_llm_api_key() -> str:
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM_API_KEY environment variable is required when AGENT_ENABLED=true")
    return api_key


# ----------------------------------------------------------------------------
# Dify 配置（已废弃，仅在 AGENT_ENABLED=false 时回退使用）
# ----------------------------------------------------------------------------
DIFY_API_URL = os.getenv("DIFY_API_URL", "https://api.dify.ai/v1/chat-messages")
DIFY_TIMEOUT_SECONDS = int(os.getenv("DIFY_TIMEOUT_SECONDS", "60"))


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
