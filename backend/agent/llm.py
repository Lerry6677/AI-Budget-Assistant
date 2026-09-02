"""LLM 工厂。

根据 config.LLM_PROVIDER 返回不同的 LangChain ChatModel 实例。

支持的 provider：
    - openai    : 通用 OpenAI 兼容协议（GPT-4o / DeepSeek / 智谱 / 月之暗面 等）
    - dashscope : 阿里云百炼 / 通义千问（langchain_community.ChatTongyi）
    - deepseek  : DeepSeek（OpenAI 兼容协议，base_url 不同）

推荐实现：
    1) 读取 config.LLM_PROVIDER
    2) 读取 config.LLM_API_KEY / LLM_BASE_URL / LLM_MODEL / LLM_TIMEOUT_SECONDS / LLM_TEMPERATURE
    3) 根据 provider 返回对应的 ChatModel

提示：
    - 加 timeout，便于网络抖动时快速失败
    - 建议加 retry：from langchain_core.runnables import RunnableConfig
    - dashscope 需要 pip install dashscope，并在环境变量设 DASHSCOPE_API_KEY
"""

from backend.config import (
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
    get_llm_api_key,
)

def get_llm():
    """LLM 工厂：根据 LLM_PROVIDER 返回对应的 ChatModel。

    支持：
        - openai    : OpenAI 兼容协议（GPT-4o / DeepSeek / 智谱 / 月之暗面 等）
        - dashscope : 阿里云百炼 / 通义千问
    """
    if LLM_PROVIDER in ("openai", "deepseek"):
        # OpenAI 兼容协议，统一用 ChatOpenAI，靠 base_url 区分厂商
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=LLM_MODEL,
            api_key=get_llm_api_key(),
            base_url=LLM_BASE_URL,
            timeout=LLM_TIMEOUT_SECONDS,
            temperature=LLM_TEMPERATURE,
        )

    if LLM_PROVIDER == "dashscope":
        # 通义千问专用客户端
        from langchain_community.chat_models import ChatTongyi
        return ChatTongyi(
            model=LLM_MODEL,
            dashscope_api_key=get_llm_api_key(),
            timeout=LLM_TIMEOUT_SECONDS,
            temperature=LLM_TEMPERATURE,
        )

    raise ValueError(f"不支持的 LLM_PROVIDER: {LLM_PROVIDER!r}")


if __name__ == "__main__":
    # 直接 python -m backend.agent.llm 时执行的最小调用示例
    llm = get_llm()
    response = llm.invoke("你好")
    print(response.content)
