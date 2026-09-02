"""L2 验证：HTTP 端到端跑通 /chat 路由→LangChain Agent→自然语言回复。

通过 monkeypatch 替换 LLM 调用，验证 HTTP 路径 + 路由分发 + 数据流，
不依赖真实 OpenAI / DeepSeek API。

用法：
    cd backend
    pytest -s tests/test_l2_agent_chat.py -v
"""
import pytest

from backend.agent.prompts import IntentResult
from backend.api.dependencies import get_current_user


def _fake_user():
    return type("U", (), {"id": 1, "username": "l2_tester"})()


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    """save_expense 不写 SQLite。"""
    monkeypatch.setattr("backend.agent.tools.DRY_RUN", True)


@pytest.fixture
def mock_classifier(monkeypatch):
    """用 monkeypatch 替换意图分类器，按 input 内容返回固定意图。"""

    def _classify(user_input: str) -> IntentResult:
        if "午饭" in user_input or "奶茶" in user_input or "晚饭" in user_input:
            return IntentResult(category="expense", confidence=0.99, reason="记账意图")
        if "多少钱" in user_input or "几笔" in user_input:
            return IntentResult(category="query", confidence=0.95, reason="查询意图")
        if "分析" in user_input:
            return IntentResult(category="analyze", confidence=0.95, reason="分析意图")
        return IntentResult(category="chat", confidence=0.95, reason="闲聊")

    # 图里 intent_node 用了 from backend.agent.prompts import classify_intent，
    # 所以 mock 必须打到 graph 模块的命名空间上（monkeypatch 不会自动改 from-import 的引用）
    monkeypatch.setattr("backend.agent.graph.classify_intent", _classify)


@pytest.fixture
def mock_llm(monkeypatch):
    """替换 router.py 里的所有 LLM 调用，避免真实网络请求。

    graph.py 里用了 from-import，所以 mock 必须同时打到 router 和 graph 命名空间。
    """
    # 1) 抽取 chain（extract）mock
    class _Extracted:
        items = [
            type(
                "It",
                (),
                {"category": "餐饮", "amount": 30.0, "description": "午饭", "time_text": "今天"},
            )()
        ]

    fake_extract = lambda: type("C", (), {"invoke": lambda self, kw: _Extracted()})()
    monkeypatch.setattr("backend.agent.router._get_extract_chain", fake_extract)
    monkeypatch.setattr("backend.agent.graph._get_extract_chain", fake_extract)

    # 2) chat chain mock
    class _ChatResp:
        content = "你好！我是 AI Budget Assistant。"

    fake_chat = lambda: type("C", (), {"invoke": lambda self, kw: _ChatResp()})()
    monkeypatch.setattr("backend.agent.router._get_chat_chain", fake_chat)
    monkeypatch.setattr("backend.agent.graph._get_chat_chain", fake_chat)


def test_chat_expense(client, mock_classifier, mock_llm):
    """expense 意图：HTTP 路径 + 路由 + 工具调用 + 自然语言回复。"""
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: _fake_user()
    try:
        resp = client.post("/chat", json={"message": "今天午饭花了30元"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        answer = data["answer"]
        assert "30" in answer, f"reply should mention 30, got: {answer}"
        assert "已记账" in answer, f"reply should contain 已记账, got: {answer}"
        print(f"\n[expense] {answer}")
    finally:
        app.dependency_overrides.clear()


def test_chat_chat(client, mock_classifier, mock_llm):
    """chat 意图：直接 LLM 闲聊回复（mock 返回）。"""
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: _fake_user()
    try:
        resp = client.post("/chat", json={"message": "你好呀"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["answer"], "回复不应为空"
        print(f"\n[chat]    {data['answer']}")
    finally:
        app.dependency_overrides.clear()


def test_query_returns_placeholder_via_graph(monkeypatch):
    """L3-1 行为：query 意图返回明确占位（"[query] 路由暂未实现..."），不是 500。

    注：本测试直接调图，绕过 HTTP 路径，避免 monkeypatch 通过 TestClient
    命名空间注入的细节问题。L2 HTTP 路径已由 test_chat_chat 覆盖。
    """
    from backend.agent.graph import run_agent

    def _classify(user_input: str):
        return IntentResult(category="query", confidence=0.95, reason="查询意图")

    monkeypatch.setattr("backend.agent.graph.classify_intent", _classify)

    reply = run_agent(user_id=1, user_input="我今天花了多少钱")
    assert "query" in reply.lower() or "未实现" in reply, f"reply: {reply}"
    print(f"\n[query_graph] {reply}")