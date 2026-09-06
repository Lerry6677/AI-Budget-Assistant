"""L3-9 / Task 19：短期 ↔ 长期 Memory 整合回归测试。

目标（只覆盖 Task 19 的最小改动本身）：
    1. 5 个业务节点完成都走 _persist_history 统一入口（A1 决策）
    2. _persist_history 跳过 "local:" 前缀的 thread（D1 决策同源）
    3. _persist_history 写失败时静默吞掉，不影响 reply（D1 决策同源）
    4. chat_node 短期层 history 拼接仍是 messages[:-1]（L3-8 行为不被破坏）
    5. 同 thread 混合意图（chat → expense → chat）下，state.messages 的结构
       仍是有意为之的"非对称"形态（H 有但 expense 的 A 没有，B1 决策）
    6. budget_node 注释与代码一致（docstring 已写 chat_history）

不覆盖：
    - 13 个历史失败用例（用户明确要求不修复）
    - 跨 thread RAG 召回准确率（决策 C1，不做 intent 过滤）
    - 新增 schema / 新向量库（用户明确禁止）
    - JWT / Dify / 前端（用户明确禁止）
"""

from __future__ import annotations

import pytest

from backend.agent import graph as graph_mod
from backend.agent.prompts import (
    BudgetParamExtractError,
    IntentResult,
    QueryParamExtractError,
)


# ----------------------------------------------------------------------------
# 共用 fixtures
# ----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    """工具走 DRY_RUN，不写真实 SQLite 账单。"""
    monkeypatch.setattr("backend.agent.tools.DRY_RUN", True)


@pytest.fixture
def fresh_graph():
    """每个测试用独立的 InMemorySaver checkpointer，测试间完全隔离。"""
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    compiled = graph_mod._build_graph(checkpointer=saver)
    yield compiled


@pytest.fixture
def save_chat_calls(monkeypatch):
    """Mock rag.save_chat，记录调用次数与参数，避免写真 DB。"""
    calls = []

    def _save(user_id, thread_id, user_input, agent_reply):
        calls.append({
            "user_id": user_id,
            "thread_id": thread_id,
            "user_input": user_input,
            "agent_reply": agent_reply,
        })
        return len(calls)

    monkeypatch.setattr("backend.agent.rag.save_chat", _save)
    return calls


# ----------------------------------------------------------------------------
# 1. helper 行为契约
# ----------------------------------------------------------------------------
class TestPersistHistoryHelper:
    def test_helper_skips_local_prefix(self, save_chat_calls):
        """thread_id 以 'local:' 开头 → 不写 chat_history。"""
        from backend.agent.state import AgentState

        state: AgentState = {
            "user_id": "u1",
            "thread_id": "local:stats",
            "input": "x",
        }
        graph_mod._persist_history(state, "x", "y")
        assert save_chat_calls == [], (
            f"local:* thread 不应写历史，实际 {save_chat_calls}"
        )

    def test_helper_writes_for_normal_thread(self, save_chat_calls):
        """普通 thread_id → 写 chat_history，参数透传。"""
        from backend.agent.state import AgentState

        state: AgentState = {
            "user_id": "u1",
            "thread_id": "main",
            "input": "hello",
        }
        graph_mod._persist_history(state, "hello", "hi there")
        assert len(save_chat_calls) == 1
        call = save_chat_calls[0]
        assert call["user_id"] == "u1"
        assert call["thread_id"] == "main"
        assert call["user_input"] == "hello"
        assert call["agent_reply"] == "hi there"

    def test_helper_swallows_save_exception(self, monkeypatch):
        """save_chat 抛异常时 helper 不抛出，不影响调用方主流程。"""
        from backend.agent.state import AgentState

        def _boom(*a, **kw):
            raise RuntimeError("DB 挂了")

        monkeypatch.setattr("backend.agent.rag.save_chat", _boom)

        state: AgentState = {"user_id": "u1", "thread_id": "main"}
        # 不应抛出
        graph_mod._persist_history(state, "x", "y")

    def test_helper_handles_missing_thread_id(self, save_chat_calls):
        """thread_id 缺失时按"非 local:"处理，走写入（与原代码行为一致）。"""
        from backend.agent.state import AgentState

        state: AgentState = {"user_id": "u1", "input": "x"}  # 无 thread_id
        graph_mod._persist_history(state, "x", "y")
        # 缺失 → 不以 "local:" 开头 → 写入（thread_id 透传为 ""）
        assert len(save_chat_calls) == 1
        assert save_chat_calls[0]["thread_id"] == ""


# ----------------------------------------------------------------------------
# 2. 5 个业务节点统一调用 _persist_history
# ----------------------------------------------------------------------------
class TestAllBusinessNodesRouteThroughHelper:
    """验证 A1 决策：expense/query/analyze/budget/chat 都经 _persist_history 落库。"""

    def test_chat_node_calls_persist_history(
        self, monkeypatch, fresh_graph
    ):
        """chat_node 完成 → _persist_history 被调一次。"""
        from langchain_core.messages import AIMessage, HumanMessage

        # 强制 chat 意图
        monkeypatch.setattr(
            "backend.agent.graph.classify_intent",
            lambda _: IntentResult(category="chat", confidence=0.99, reason="chat"),
        )

        called = {"count": 0}

        def _spy(state, user_input, reply):
            called["count"] += 1

        monkeypatch.setattr("backend.agent.graph._persist_history", _spy)

        # mock chat_chain
        class _R:
            content = "pong"

        monkeypatch.setattr(
            "backend.agent.graph._get_chat_chain",
            lambda: type("C", (), {"invoke": staticmethod(lambda _: _R())})(),
        )

        fresh_graph.invoke(
            {"user_id": "u1", "input": "hi", "thread_id": "main"},
            config={"configurable": {"thread_id": "main"}},
        )
        assert called["count"] == 1, (
            f"chat_node 应调一次 _persist_history，实际 {called['count']}"
        )

    def test_expense_node_calls_persist_history(self, monkeypatch, fresh_graph):
        """expense_node 完成 → _persist_history 被调一次。"""
        monkeypatch.setattr(
            "backend.agent.graph.classify_intent",
            lambda _: IntentResult(category="expense", confidence=0.99, reason="expense"),
        )

        # mock extract chain（不依赖 LLM）
        class _It:
            category = "餐饮"
            amount = 30.0
            description = "午饭"
            time_text = "今天"

        class _Extracted:
            items = [_It()]

        monkeypatch.setattr(
            "backend.agent.graph._get_extract_chain",
            lambda: type("C", (), {"invoke": staticmethod(lambda _: _Extracted())})(),
        )

        called = {"count": 0}
        monkeypatch.setattr(
            "backend.agent.graph._persist_history",
            lambda state, ui, r: called.__setitem__("count", called["count"] + 1),
        )

        fresh_graph.invoke(
            {"user_id": "u1", "input": "今天午饭30元", "thread_id": "main"},
            config={"configurable": {"thread_id": "main"}},
        )
        assert called["count"] == 1

    def test_query_node_calls_persist_history(self, monkeypatch, fresh_graph):
        """query_node 完成 → _persist_history 被调一次。"""
        from backend.agent.prompts import QueryParams

        monkeypatch.setattr(
            "backend.agent.graph.classify_intent",
            lambda _: IntentResult(category="query", confidence=0.95, reason="query"),
        )
        monkeypatch.setattr(
            "backend.agent.graph.classify_query_params",
            lambda _: QueryParams(start_date=None, end_date=None, category=None),
        )

        called = {"count": 0}
        monkeypatch.setattr(
            "backend.agent.graph._persist_history",
            lambda state, ui, r: called.__setitem__("count", called["count"] + 1),
        )

        fresh_graph.invoke(
            {"user_id": "u1", "input": "我今天花了多少", "thread_id": "main"},
            config={"configurable": {"thread_id": "main"}},
        )
        assert called["count"] == 1

    def test_analyze_node_calls_persist_history(self, monkeypatch, fresh_graph):
        """analyze_node 完成 → _persist_history 被调一次。"""
        from backend.agent.prompts import QueryParams

        monkeypatch.setattr(
            "backend.agent.graph.classify_intent",
            lambda _: IntentResult(category="analyze", confidence=0.95, reason="analyze"),
        )
        monkeypatch.setattr(
            "backend.agent.graph.classify_query_params",
            lambda _: QueryParams(start_date=None, end_date=None, category=None),
        )

        called = {"count": 0}
        monkeypatch.setattr(
            "backend.agent.graph._persist_history",
            lambda state, ui, r: called.__setitem__("count", called["count"] + 1),
        )

        fresh_graph.invoke(
            {"user_id": "u1", "input": "分析下本月", "thread_id": "main"},
            config={"configurable": {"thread_id": "main"}},
        )
        assert called["count"] == 1

    def test_budget_node_calls_persist_history(self, monkeypatch, fresh_graph):
        """budget_node 完成 → _persist_history 被调一次（D1：注释与代码一致）。"""
        from backend.agent.prompts import BudgetParams

        monkeypatch.setattr(
            "backend.agent.graph.classify_intent",
            lambda _: IntentResult(category="budget", confidence=0.95, reason="budget"),
        )
        monkeypatch.setattr(
            "backend.agent.graph.classify_budget_params",
            lambda _: BudgetParams(savings_goal=5000, financial_goal="买车"),
        )

        called = {"count": 0}
        monkeypatch.setattr(
            "backend.agent.graph._persist_history",
            lambda state, ui, r: called.__setitem__("count", called["count"] + 1),
        )

        fresh_graph.invoke(
            {"user_id": "u1", "input": "每月存5000", "thread_id": "main"},
            config={"configurable": {"thread_id": "main"}},
        )
        assert called["count"] == 1, (
            "budget_node 必须也走 _persist_history（D1 决策）"
        )


# ----------------------------------------------------------------------------
# 3. local: 前缀在端到端路径上被 helper 跳过
# ----------------------------------------------------------------------------
class TestLocalThreadEndToEnd:
    def test_local_thread_does_not_persist(
        self, monkeypatch, fresh_graph, save_chat_calls
    ):
        """thread_id 以 'local:' 开头时，chat_node 不写 chat_history。"""
        monkeypatch.setattr(
            "backend.agent.graph.classify_intent",
            lambda _: IntentResult(category="chat", confidence=0.99, reason="chat"),
        )

        class _R:
            content = "pong"

        monkeypatch.setattr(
            "backend.agent.graph._get_chat_chain",
            lambda: type("C", (), {"invoke": staticmethod(lambda _: _R())})(),
        )

        fresh_graph.invoke(
            {"user_id": "u1", "input": "hi", "thread_id": "local:stats"},
            config={"configurable": {"thread_id": "local:stats"}},
        )
        assert save_chat_calls == [], (
            f"local:* thread 不应触发 save_chat，实际 {save_chat_calls}"
        )


# ----------------------------------------------------------------------------
# 4. chat_node 短期层 history 拼接（来自 L3-8）未被破坏
# ----------------------------------------------------------------------------
class TestChatShortMemorySlice:
    def test_history_slice_still_excludes_current_input(
        self, monkeypatch, fresh_graph
    ):
        """L3-8 行为不变：chat_node 的 history = state["messages"][:-1]，剥离本轮。"""
        captured = {"histories": []}

        class _R:
            content = "pong"

        def _invoke(kwargs):
            captured["histories"].append(kwargs.get("history", []))
            return _R()

        monkeypatch.setattr(
            "backend.agent.graph.classify_intent",
            lambda _: IntentResult(category="chat", confidence=0.99, reason="chat"),
        )
        monkeypatch.setattr(
            "backend.agent.graph._get_chat_chain",
            lambda: type("C", (), {"invoke": staticmethod(_invoke)})(),
        )

        cfg = {"configurable": {"thread_id": "main"}}
        fresh_graph.invoke(
            {"user_id": "u1", "input": "first", "thread_id": "main"},
            config=cfg,
        )
        fresh_graph.invoke(
            {"user_id": "u1", "input": "second", "thread_id": "main"},
            config=cfg,
        )

        # 第 2 次 invoke 时 history 应包含第 1 轮 H+A，但不含本轮 "second"
        second_history = captured["histories"][1]
        contents = [m.content for m in second_history]
        assert "first" in contents
        assert "second" not in contents


# ----------------------------------------------------------------------------
# 5. 混合意图下短期层结构（B1 决策：有意为之）
# ----------------------------------------------------------------------------
class TestMixedIntentShortMemoryShape:
    """chat → expense → chat 后，state.messages 应是
       [H_chat, A_chat, H_expense, H_chat2, A_chat2] —— expense_node 的
       reply 不在短期层里（B1 决策保留），前端通过 chat_history 长期层拿到完整流。
    """

    def test_mixed_intent_messages_shape(
        self, monkeypatch, fresh_graph
    ):
        from langchain_core.messages import AIMessage, HumanMessage

        # 轮 1：chat（直接走 chat_chain）
        # 轮 2：expense（走 extract + save_expense，但 save_expense DRY_RUN）
        # 轮 3：chat
        intents = iter([
            IntentResult(category="chat", confidence=0.99, reason="c"),
            IntentResult(category="expense", confidence=0.99, reason="e"),
            IntentResult(category="chat", confidence=0.99, reason="c"),
        ])
        monkeypatch.setattr(
            "backend.agent.graph.classify_intent",
            lambda _: next(intents),
        )

        class _Extracted:
            class _It:
                category = "餐饮"
                amount = 30.0
                description = "午饭"
                time_text = "今天"
            items = [_It()]

        monkeypatch.setattr(
            "backend.agent.graph._get_extract_chain",
            lambda: type("C", (), {"invoke": staticmethod(lambda _: _Extracted())})(),
        )

        class _R:
            content = "pong"

        monkeypatch.setattr(
            "backend.agent.graph._get_chat_chain",
            lambda: type("C", (), {"invoke": staticmethod(lambda _: _R())})(),
        )

        cfg = {"configurable": {"thread_id": "mix"}}
        for msg in ["c1", "e1", "c2"]:
            fresh_graph.invoke(
                {"user_id": "u1", "input": msg, "thread_id": "mix"},
                config=cfg,
            )

        saved = fresh_graph.get_state(cfg)
        msgs = saved.values.get("messages", [])
        human = [m.content for m in msgs if isinstance(m, HumanMessage)]
        ai = [m.content for m in msgs if isinstance(m, AIMessage)]

        # 3 个 HumanMessage
        assert human == ["c1", "e1", "c2"], f"unexpected H: {human}"
        # 只 2 个 AIMessage（来自 2 个 chat_node），expense_node 不写 A（B1 决策）
        assert ai == ["pong", "pong"], (
            f"短期层 AI 应只来自 chat_node（B1 决策），实际 {ai}"
        )


# ----------------------------------------------------------------------------
# 6. budget_node 注释已与代码一致（D1 决策静态校验）
# ----------------------------------------------------------------------------
def test_budget_node_docstring_no_longer_says_no_persist():
    """D1：budget_node docstring 不再声称'不写 chat_history'。"""
    import inspect

    doc = inspect.getdoc(graph_mod.budget_node) or ""
    assert "不写 chat_history" not in doc, (
        "D1 决策：docstring 仍声称不写 chat_history，但代码已写"
    )
    # 写有 _persist_history 的引用作为正断言
    assert "_persist_history" in doc, (
        "docstring 应明确说明 budget_node 经 _persist_history 写历史"
    )
