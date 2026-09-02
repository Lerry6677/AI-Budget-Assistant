"""L3-2 Memory / Checkpointer 测试。

目标：验证 LangGraph 状态在多轮对话中累积，且按 thread_id 隔离。
所有 LLM 依赖通过 monkeypatch 替换；save_expense 走 DRY_RUN 避免写真 DB。
"""

import os

import pytest

from backend.agent import graph as graph_mod
from backend.agent.state import AgentState


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    """整个模块默认走 DRY_RUN，save_expense 不写库。"""
    monkeypatch.setattr("backend.agent.tools.DRY_RUN", True)


@pytest.fixture
def fresh_graph():
    """每个测试用独立的 InMemorySaver checkpointer，测试间完全隔离。"""
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    compiled = graph_mod._build_graph(checkpointer=saver)
    yield compiled


@pytest.fixture
def mock_intent(monkeypatch):
    """Mock 意图分类：包含特定关键字 → expense，否则 chat。"""
    from backend.agent.prompts import IntentResult

    def _classify(user_input: str) -> IntentResult:
        if any(k in user_input for k in ("午饭", "奶茶", "晚饭", "早饭", "打车")):
            return IntentResult(category="expense", confidence=0.99, reason="记账")
        return IntentResult(category="chat", confidence=0.95, reason="闲聊")

    monkeypatch.setattr("backend.agent.graph.classify_intent", _classify)
    return _classify


@pytest.fixture
def mock_chat_chain(monkeypatch):
    """Mock chat_chain：返回固定 'pong'。"""
    class _FakeResult:
        content = "pong"

    def _invoke(_):
        return _FakeResult()

    chain = type("C", (), {"invoke": staticmethod(_invoke)})()
    monkeypatch.setattr("backend.agent.graph._get_chat_chain", lambda: chain)


@pytest.fixture
def mock_extract_chain(monkeypatch):
    """Mock extract_chain：返回固定 ExpenseList（动态 type，结构与 router 一致）。"""
    class _ExtractedItems:
        items = [
            type("It", (), {"category": "餐饮", "amount": 30.0, "description": "午饭", "time_text": "今天"})()
        ]

    chain = type("C", (), {"invoke": staticmethod(lambda _: _ExtractedItems())})()
    monkeypatch.setattr("backend.agent.graph._get_extract_chain", lambda: chain)


# ----------------------------------------------------------------------------
# 核心测试
# ----------------------------------------------------------------------------
def test_thread_isolation(
    fresh_graph, mock_intent, mock_chat_chain, mock_extract_chain
):
    """两个 user 的 state 互不串扰（不同 thread_id = 不同 state）。"""
    # User A 记一笔
    state_a_1 = fresh_graph.invoke(
        {"user_id": "A", "input": "今天午饭30元"},
        config={"configurable": {"thread_id": "user_A"}},
    )
    assert "已记账" in state_a_1["reply"]

    # User B 问一句
    state_b = fresh_graph.invoke(
        {"user_id": "B", "input": "你好"},
        config={"configurable": {"thread_id": "user_B"}},
    )
    assert state_b["reply"] == "pong"

    # User A 继续：state 应保留之前消息
    state_a_2 = fresh_graph.invoke(
        {"user_id": "A", "input": "再来一杯奶茶20元"},
        config={"configurable": {"thread_id": "user_A"}},
    )
    # 消息历史应当累积到 2 条 HumanMessage
    msgs = state_a_2["messages"]
    human_msgs = [m for m in msgs if m.type == "human"]
    assert len(human_msgs) == 2, f"User A 应有 2 条 HumanMessage，实际 {len(human_msgs)}"
    assert any("奶茶" in m.content for m in human_msgs)

    # User B 继续：state 应有自己的 2 条 HumanMessage（隔离成功，A 的"奶茶"不应出现）
    state_b_2 = fresh_graph.invoke(
        {"user_id": "B", "input": "今天晚饭50元"},
        config={"configurable": {"thread_id": "user_B"}},
    )
    msgs_b = state_b_2["messages"]
    human_msgs_b = [m for m in msgs_b if m.type == "human"]
    assert len(human_msgs_b) == 2, f"User B 应有 2 条 HumanMessage，实际 {len(human_msgs_b)}"
    # 关键：User A 的 "奶茶" 不应泄漏到 User B
    assert not any("奶茶" in m.content for m in human_msgs_b), "User A 的消息泄漏到 User B"
    # User B 的消息应包含自己的两轮
    b_contents = [m.content for m in human_msgs_b]
    assert b_contents == ["你好", "今天晚饭50元"]


def test_multi_turn_messages_accumulate(
    fresh_graph, mock_intent, mock_chat_chain, mock_extract_chain
):
    """同一 thread 多轮：messages 字段按 add_messages reducer 累积。"""
    cfg = {"configurable": {"thread_id": "user_X"}}

    fresh_graph.invoke({"user_id": "X", "input": "今天午饭30元"}, config=cfg)
    fresh_graph.invoke({"user_id": "X", "input": "今天晚饭50元"}, config=cfg)
    s3 = fresh_graph.invoke({"user_id": "X", "input": "你好"}, config=cfg)

    # 三轮后应有 3 条 HumanMessage
    human_msgs = [m for m in s3["messages"] if m.type == "human"]
    assert len(human_msgs) == 3
    assert [m.content for m in human_msgs] == [
        "今天午饭30元",
        "今天晚饭50元",
        "你好",
    ]


def test_run_agent_accepts_thread_id(
    monkeypatch, mock_intent, mock_chat_chain, mock_extract_chain
):
    """run_agent 传 thread_id 走 checkpointer 路径不报错。"""
    # 强制重置单例，确保下一次 get_graph() 重新构造（用 monkeypatch 替换 checkpointer）
    monkeypatch.setattr(
        "backend.agent.graph._get_checkpointer",
        lambda: _make_inmemory_saver(),
    )
    graph_mod.reset_graph_for_tests()

    # 第一次
    r1 = graph_mod.run_agent(user_id="u2", user_input="今天午饭30元", thread_id="user_u2")
    assert "已记账" in r1
    # 第二次：state 应累积
    r2 = graph_mod.run_agent(user_id="u2", user_input="今天晚饭50元", thread_id="user_u2")
    assert "已记账" in r2

    # 验证：直接 get_graph 拿 state 能看到 2 条 HumanMessage
    g = graph_mod.get_graph()
    state = g.get_state({"configurable": {"thread_id": "user_u2"}})
    human_msgs = [m for m in state.values["messages"] if m.type == "human"]
    assert len(human_msgs) == 2


def _make_inmemory_saver():
    from langgraph.checkpoint.memory import InMemorySaver
    return InMemorySaver()


# ----------------------------------------------------------------------------
# SqliteSaver 真实文件测试（端到端最弱检验）
# ----------------------------------------------------------------------------
def test_sqlite_saver_creates_db_file(
    monkeypatch, mock_intent, mock_chat_chain, mock_extract_chain
):
    """SqliteSaver 工作：第一次 run_agent 后，backend/checkpoints.sqlite 文件应存在。

    已知限制：
        - 全量跑时单例 _graph 已被前序测试构造过，文件可能已存在。
          因此这里只在文件不存在时检查。
        - Windows 上 sqlite3 锁不会立即释放，teardown 不能删文件。
    """
    db_path = os.path.join(
        os.path.dirname(graph_mod.__file__), "..", "checkpoints.sqlite"
    )
    db_path = os.path.abspath(db_path)

    # 重置单例（让第一次调 get_graph 时走 SqliteSaver 路径）
    graph_mod.reset_graph_for_tests()
    # 同时重置 checkpointer 单例（之前可能已被注入为 InMemorySaver）
    monkeypatch.setattr("backend.agent.graph._checkpointer", None)

    file_existed_before = os.path.exists(db_path)

    graph_mod.run_agent(user_id="u3", user_input="今天午饭30元", thread_id="user_u3")

    # 文件现在应存在
    assert os.path.exists(db_path), f"期望 {db_path} 存在"
    print(f"\n[sqlite] file existed_before={file_existed_before}, after={os.path.exists(db_path)}")
    # 不删文件：Windows 上 sqlite3 锁 + 跨测试共享单例
    # 文件可以被后续 run 覆盖，不影响功能
