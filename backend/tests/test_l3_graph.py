"""L3-1 验证：最小 LangGraph StateGraph。

测试目标：
    1. 图能编译（get_graph() 不抛错）
    2. 路由函数（_route_after_intent）正确返回节点名
    3. expense 流端到端跑通：今天午饭30元 → expense_node → save_expense → reply
    4. chat 流端到端跑通：你好 → chat_node → LLM → reply
    5. 流式 stream 能观察到 state 在节点间流转

通过 monkeypatch 替换 LLM 调用，避免真实 API 请求。
"""
import pytest

from backend.agent.graph import _route_after_intent, get_graph, run_agent
from backend.agent.prompts import IntentResult
from backend.agent.state import AgentState


# ---------- mock 辅助 ----------

def _mock_intent_router(monkeypatch):
    """按 input 内容返回不同意图，绕过真实 LLM 分类。"""

    def _classify(user_input: str) -> IntentResult:
        if any(k in user_input for k in ("午饭", "奶茶", "晚饭", "打车")):
            return IntentResult(category="expense", confidence=0.99, reason="记账")
        return IntentResult(category="chat", confidence=0.95, reason="闲聊")

    # 打到 graph 模块的命名空间（图里用了 from-import）
    monkeypatch.setattr("backend.agent.graph.classify_intent", _classify)


def _mock_llm(monkeypatch):
    """mock router.py 里的 extract chain 和 chat chain。"""

    class _ExtractedItems:
        items = [
            type(
                "It",
                (),
                {"category": "餐饮", "amount": 30.0, "description": "午饭", "time_text": "今天"},
            )()
        ]

    monkeypatch.setattr(
        "backend.agent.graph._get_extract_chain",
        lambda: type("C", (), {"invoke": lambda self, kw: _ExtractedItems()})(),
    )

    class _ChatResp:
        content = "你好！我是 AI Budget Assistant。"

    monkeypatch.setattr(
        "backend.agent.graph._get_chat_chain",
        lambda: type("C", (), {"invoke": lambda self, kw: _ChatResp()})(),
    )


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    monkeypatch.setattr("backend.agent.tools.DRY_RUN", True)


# ---------- 测试 ----------

def test_graph_can_be_built():
    """图能成功编译（add_node / add_edge / add_conditional_edges 不报错）。"""
    graph = get_graph()
    assert graph is not None


def test_route_after_intent():
    """路由函数：读 state["intent"]，返回节点名。"""
    assert _route_after_intent({"intent": "expense"}) == "expense"
    assert _route_after_intent({"intent": "chat"}) == "chat"


def test_expense_flow(monkeypatch):
    """完整 expense 流：今天午饭30元 → expense_node → save_expense → reply。"""
    _mock_intent_router(monkeypatch)
    _mock_llm(monkeypatch)

    reply = run_agent(user_id="u1", user_input="今天午饭花了30元")
    assert "已记账" in reply, f"reply should contain 已记账, got: {reply}"
    assert "30" in reply, f"reply should mention 30, got: {reply}"
    print(f"\n[expense_flow] {reply}")


def test_chat_flow(monkeypatch):
    """完整 chat 流：你好 → chat_node → LLM → reply。"""
    _mock_intent_router(monkeypatch)
    _mock_llm(monkeypatch)

    reply = run_agent(user_id="u1", user_input="你好呀")
    assert reply, "reply should not be empty"
    print(f"\n[chat_flow] {reply}")


def test_graph_stream_observable(monkeypatch):
    """LangGraph 独有：graph.stream() 能观察每个节点的 state 更新。

    对 Python if/else dispatch 来说是不可能做到的——这是 LangGraph 的核心优势。
    """
    _mock_intent_router(monkeypatch)
    _mock_llm(monkeypatch)

    graph = get_graph()
    # L3-2 起图默认挂 SqliteSaver，stream 必须传 config（thread_id）
    events = list(graph.stream(
        {"user_id": "u1", "input": "今天午饭花了30元"},
        config={"configurable": {"thread_id": "anon_test_stream"}},
    ))

    # 每个事件是一个 {node_name: state_delta}
    node_names = [list(e.keys())[0] for e in events]
    print(f"\n[stream_nodes] {node_names}")

    assert "intent_node" in node_names, "intent_node must execute"
    assert "expense_node" in node_names, "expense_node must execute for expense input"
    # 最终事件的最后一个节点
    last_node = node_names[-1]
    last_state_delta = events[-1][last_node]
    assert "reply" in last_state_delta, "final node must set reply"
    assert "已记账" in last_state_delta["reply"]


def test_graph_chat_stream(monkeypatch):
    """chat 流也能 stream。"""
    _mock_intent_router(monkeypatch)
    _mock_llm(monkeypatch)

    graph = get_graph()
    events = list(graph.stream(
        {"user_id": "u1", "input": "你好呀"},
        config={"configurable": {"thread_id": "anon_test_chat_stream"}},
    ))
    node_names = [list(e.keys())[0] for e in events]

    assert "intent_node" in node_names
    assert "chat_node" in node_names
    assert "expense_node" not in node_names, "chat 输入不应该走到 expense_node"
    print(f"\n[chat_stream_nodes] {node_names}")