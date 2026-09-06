"""L3-8：短期 Memory（AgentState.messages）真正被 chat_node 消费。

目标：
    - 验证 chat_node 把当前 thread 的 messages 拼成 LLM 的 history
    - 验证 chat_node 把 AIMessage 写回 messages（add_messages reducer 持久化）
    - 验证 thread 隔离
    - 验证本轮 input 不在 history 中重复出现

所有 LLM 依赖通过 monkeypatch 替换；save_expense / save_chat 通过
全局 DRY_RUN fixture + monkeypatch 替代，避免写真实 DB。
"""

from __future__ import annotations

import pytest

from backend.agent import graph as graph_mod
from backend.agent.prompts import IntentResult


# ----------------------------------------------------------------------------
# 共用 fixtures
# ----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    """让工具走 DRY_RUN，不写真实 SQLite 账单 / chat_history。"""
    monkeypatch.setattr("backend.agent.tools.DRY_RUN", True)
    # chat_node 内部调 rag.save_chat —— 让它安静失败，避免依赖 RAG 测试库
    monkeypatch.setattr("backend.agent.rag.save_chat", lambda *a, **kw: -1)


@pytest.fixture
def fresh_graph():
    """每个测试用独立的 InMemorySaver checkpointer，测试间完全隔离。"""
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    compiled = graph_mod._build_graph(checkpointer=saver)
    yield compiled


class _Calls(list):
    """record 每次 chat_chain.invoke 的 kwargs，便于断言。"""


@pytest.fixture
def mock_chat_chain_recording(monkeypatch):
    """Mock chat_chain：记录每次 invoke 的 kwargs，返回固定 reply。"""
    calls = _Calls()

    class _FakeResult:
        def __init__(self, content: str):
            self.content = content

    def _invoke(kwargs):
        calls.append(kwargs)
        return _FakeResult("pong")

    chain = type("C", (), {"invoke": staticmethod(_invoke)})()

    # graph 通过 from-import 拿到 _get_chat_chain，必须打到 graph 命名空间
    monkeypatch.setattr("backend.agent.graph._get_chat_chain", lambda: chain)
    return calls


@pytest.fixture
def mock_intent_chat(monkeypatch):
    """强制所有输入都走 chat 意图。"""

    def _classify(user_input: str) -> IntentResult:
        return IntentResult(category="chat", confidence=0.99, reason="闲聊")

    monkeypatch.setattr("backend.agent.graph.classify_intent", _classify)
    return _classify


# ----------------------------------------------------------------------------
# 1. 同 thread 第二轮 chat 看到第一轮的 HumanMessage
# ----------------------------------------------------------------------------
def test_second_turn_sees_first_human_message(
    fresh_graph, mock_chat_chain_recording, mock_intent_chat
):
    cfg = {"configurable": {"thread_id": "main"}}

    # 第一轮
    fresh_graph.invoke(
        {"user_id": "u1", "input": "我喜欢喝咖啡", "thread_id": "main"},
        config=cfg,
    )
    # 第二轮
    fresh_graph.invoke(
        {"user_id": "u1", "input": "我最近喜欢喝什么？", "thread_id": "main"},
        config=cfg,
    )

    assert len(mock_chat_chain_recording) == 2
    second_kwargs = mock_chat_chain_recording[1]

    history = second_kwargs.get("history", [])
    history_contents = [m.content for m in history]
    # 关键断言：第二轮 invoke 时 history 含第一轮的 HumanMessage
    assert any("咖啡" in c for c in history_contents), (
        f"第二轮 history 应包含第一轮 '咖啡'，实际 {history_contents}"
    )
    # 第二轮的 input 仍由 ("human","{input}") 显式提供，不依赖 history
    assert second_kwargs["input"] == "我最近喜欢喝什么？"


# ----------------------------------------------------------------------------
# 2. chat_node 把 AIMessage 写回 messages（add_messages reducer 持久化）
# ----------------------------------------------------------------------------
def test_chat_node_appends_ai_message_to_state(
    fresh_graph, mock_chat_chain_recording, mock_intent_chat
):
    cfg = {"configurable": {"thread_id": "main"}}

    s1 = fresh_graph.invoke(
        {"user_id": "u1", "input": "我喜欢喝咖啡", "thread_id": "main"},
        config=cfg,
    )
    s2 = fresh_graph.invoke(
        {"user_id": "u1", "input": "再来一句", "thread_id": "main"},
        config=cfg,
    )

    # 第一轮后 messages 应含 1 human + 1 ai
    ai_msgs_s1 = [m for m in s1["messages"] if m.type == "ai"]
    assert len(ai_msgs_s1) == 1, f"第一轮应有 1 条 AIMessage，实际 {len(ai_msgs_s1)}"
    assert ai_msgs_s1[0].content == "pong"

    # 第二轮后 messages 应累积：2 human + 2 ai
    human_msgs_s2 = [m for m in s2["messages"] if m.type == "human"]
    ai_msgs_s2 = [m for m in s2["messages"] if m.type == "ai"]
    assert len(human_msgs_s2) == 2
    assert len(ai_msgs_s2) == 2
    assert [m.content for m in human_msgs_s2] == ["我喜欢喝咖啡", "再来一句"]
    assert all(m.content == "pong" for m in ai_msgs_s2)


# ----------------------------------------------------------------------------
# 3. thread 隔离：不同 thread 不串记忆
# ----------------------------------------------------------------------------
def test_threads_do_not_share_short_memory(
    fresh_graph, mock_chat_chain_recording, mock_intent_chat
):
    cfg_a = {"configurable": {"thread_id": "thread_A"}}
    cfg_b = {"configurable": {"thread_id": "thread_B"}}

    fresh_graph.invoke(
        {"user_id": "u1", "input": "我喜欢喝咖啡", "thread_id": "thread_A"},
        config=cfg_a,
    )
    fresh_graph.invoke(
        {"user_id": "u1", "input": "我喜欢喝茶", "thread_id": "thread_B"},
        config=cfg_b,
    )
    fresh_graph.invoke(
        {"user_id": "u1", "input": "我喜欢喝什么？", "thread_id": "thread_A"},
        config=cfg_a,
    )

    # 第 3 次 invoke 是 thread_A 的第二轮，history 应只含 "咖啡"，不含 "茶"
    third_kwargs = mock_chat_chain_recording[2]
    history = third_kwargs.get("history", [])
    history_contents = [m.content for m in history]
    assert any("咖啡" in c for c in history_contents)
    assert not any("茶" in c for c in history_contents), (
        f"thread_A 不应看到 thread_B 的 '茶'，实际 {history_contents}"
    )


# ----------------------------------------------------------------------------
# 4. 本轮 input 不在 history 中重复出现
# ----------------------------------------------------------------------------
def test_current_input_not_duplicated_in_history(
    fresh_graph, mock_chat_chain_recording, mock_intent_chat
):
    cfg = {"configurable": {"thread_id": "main"}}

    fresh_graph.invoke(
        {"user_id": "u1", "input": "我喜欢喝咖啡", "thread_id": "main"},
        config=cfg,
    )
    fresh_graph.invoke(
        {"user_id": "u1", "input": "再来一句", "thread_id": "main"},
        config=cfg,
    )

    second_kwargs = mock_chat_chain_recording[1]
    history = second_kwargs.get("history", [])
    history_contents = [m.content for m in history]

    # history 应包含第 1 轮的 HumanMessage，但不应包含本轮 "再来一句"
    assert "我喜欢喝咖啡" in history_contents
    assert "再来一句" not in history_contents, (
        f"本轮 input '再来一句' 不应出现在 history，实际 {history_contents}"
    )
    # 顶层 ("human","{input}") 单独提供本轮
    assert second_kwargs["input"] == "再来一句"


# ----------------------------------------------------------------------------
# 5. 第一轮（无历史）时 history 为空列表，不报错
# ----------------------------------------------------------------------------
def test_first_turn_history_is_empty(
    fresh_graph, mock_chat_chain_recording, mock_intent_chat
):
    cfg = {"configurable": {"thread_id": "main"}}

    fresh_graph.invoke(
        {"user_id": "u1", "input": "你好", "thread_id": "main"},
        config=cfg,
    )

    first_kwargs = mock_chat_chain_recording[0]
    history = first_kwargs.get("history", [])
    # 第一轮没有任何前置 HumanMessage，history 应当是空列表（不是 None）
    assert history == [], f"第一轮 history 应为空列表，实际 {history!r}"


# ----------------------------------------------------------------------------
# 6. SqliteSaver 真实持久化：跨 invoke 后 state.messages 累积（端到端最弱检验）
# ----------------------------------------------------------------------------
def test_sqlite_saver_round_trip_short_memory(
    monkeypatch, mock_chat_chain_recording, mock_intent_chat
):
    """跨 run_agent 两次调用后，第二次 invoke 的 chat_chain history 包含第一轮。

    用 monkeypatch 替换 _get_checkpointer 为 InMemorySaver，避免依赖真实 sqlite 文件锁。
    """
    from langgraph.checkpoint.memory import InMemorySaver

    monkeypatch.setattr(
        "backend.agent.graph._get_checkpointer",
        lambda: InMemorySaver(),
    )
    graph_mod.reset_graph_for_tests()

    graph_mod.run_agent(
        user_id="u_rt", user_input="我喜欢喝咖啡", thread_id="main"
    )
    graph_mod.run_agent(
        user_id="u_rt", user_input="再来一句", thread_id="main"
    )

    # 第二次 run_agent 应使 history 包含第一轮的 "咖啡"
    second_kwargs = mock_chat_chain_recording[1]
    history = second_kwargs.get("history", [])
    history_contents = [m.content for m in history]
    assert any("咖啡" in c for c in history_contents), (
        f"第二次 invoke 应看到第一轮历史，实际 {history_contents}"
    )


# =============================================================================
# Task 18：短期 Memory 窗口截断测试
# =============================================================================
# chat_node 在拼 history 时只取最近 MAX_SHORT_MEMORY_MESSAGES 条，
# 防止 thread 长期使用后上下文无界增长。
# - 仅截断"喂给 LLM 的 history"，不影响 SqliteSaver 持久化。
# - 按消息对（human + ai）成对截断，不切到一半对话。
def test_history_window_truncates_old_messages(
    fresh_graph, mock_chat_chain_recording, mock_intent_chat
):
    """超过窗口的历史被截断，最近 N 条仍保留。

    MAX_SHORT_MEMORY_MESSAGES = 20 → 喂给 LLM 的 history 最多 20 条。
    跑 15 轮（每轮 1 human + 1 ai = 30 条 messages），第 16 轮 invoke 时：
    - history 长度 ≤ 20
    - history 不含第 1~5 轮的 HumanMessage（最早 10 条被截断）
    - history 仍含第 6~15 轮的最近内容
    """
    from backend.agent.graph import MAX_SHORT_MEMORY_MESSAGES

    cfg = {"configurable": {"thread_id": "window_t"}}

    # 15 轮对话，每轮 user 说一句话，agent 回 pong
    num_turns = 15
    for i in range(num_turns):
        fresh_graph.invoke(
            {"user_id": "uw", "input": f"turn{i}_user", "thread_id": "window_t"},
            config=cfg,
        )

    # 第 16 轮：触发窗口截断
    fresh_graph.invoke(
        {"user_id": "uw", "input": "turn16_user", "thread_id": "window_t"},
        config=cfg,
    )

    # 第 16 次 invoke 是 index 15
    last_kwargs = mock_chat_chain_recording[num_turns]
    history = last_kwargs.get("history", [])
    assert len(history) <= MAX_SHORT_MEMORY_MESSAGES, (
        f"history 应被截断到 ≤{MAX_SHORT_MEMORY_MESSAGES}，实际 {len(history)}"
    )
    history_contents = [m.content for m in history]

    # 最早的几轮应该被截掉（30 条 messages 减窗口 20 = 前 10 条丢失）
    for old in [f"turn{i}_user" for i in range(5)]:
        assert old not in history_contents, (
            f"历史 {old!r} 应被窗口截断，实际仍在 history: {history_contents}"
        )

    # 最近几轮必须保留（最近一条 HumanMessage 倒数第 2 条）
    assert f"turn{num_turns - 1}_user" in history_contents, (
        f"最近一轮 {f'turn{num_turns-1}_user'!r} 应在 history，实际 {history_contents}"
    )


def test_history_window_keeps_recent_context(
    fresh_graph, mock_chat_chain_recording, mock_intent_chat
):
    """窗口只截断远的，不影响近的：最近一轮内容仍在 history。

    跑 5 轮对话，最后一轮问"上一轮我说了什么"。
    验证：第 5 轮的 history 含第 4 轮的 HumanMessage（窗口没误伤近期上下文）。
    """
    cfg = {"configurable": {"thread_id": "recent_t"}}

    for i in range(4):
        fresh_graph.invoke(
            {"user_id": "ur", "input": f"earlier{i}", "thread_id": "recent_t"},
            config=cfg,
        )
    fresh_graph.invoke(
        {"user_id": "ur", "input": "上一轮我说了什么", "thread_id": "recent_t"},
        config=cfg,
    )

    last_kwargs = mock_chat_chain_recording[4]
    history = last_kwargs.get("history", [])
    history_contents = [m.content for m in history]
    assert "earlier3" in history_contents, (
        f"上一轮 'earlier3' 应在 history（窗口不该切掉它），实际 {history_contents}"
    )


def test_short_memory_window_does_not_affect_state_messages(
    fresh_graph, mock_chat_chain_recording, mock_intent_chat
):
    """窗口仅影响"喂给 LLM 的 history"，不影响 SqliteSaver 持久化的 messages。

    跑 15 轮（30 条 messages）。
    - 第 16 轮 chat_chain 收到的 history 长度 ≤ 20（被截断）
    - 但 graph.get_state() 取出的 state["messages"] 仍是完整 30 条（没丢）
    """
    from backend.agent.graph import MAX_SHORT_MEMORY_MESSAGES

    cfg = {"configurable": {"thread_id": "persist_t"}}

    num_turns = 15
    for i in range(num_turns):
        fresh_graph.invoke(
            {"user_id": "up", "input": f"pturn{i}", "thread_id": "persist_t"},
            config=cfg,
        )

    # 触发出第 16 轮：history 应被截断
    fresh_graph.invoke(
        {"user_id": "up", "input": "pturn_last", "thread_id": "persist_t"},
        config=cfg,
    )
    last_kwargs = mock_chat_chain_recording[num_turns]
    history = last_kwargs.get("history", [])
    assert len(history) <= MAX_SHORT_MEMORY_MESSAGES, (
        f"chat history 应被窗口截断，实际 {len(history)}"
    )

    # 但 SqliteSaver 里的 state.messages 仍是全部：每轮 1 human + 1 ai，
    # 共 (num_turns + 1) 对（第 16 轮的 HumanMessage + AIMessage 都已持久化）。
    saved_state = fresh_graph.get_state(cfg)
    saved_msgs = saved_state.values.get("messages", [])
    human_msgs = [m for m in saved_msgs if m.type == "human"]
    ai_msgs = [m for m in saved_msgs if m.type == "ai"]
    # 第 16 轮的 HumanMessage 也已 push 进 state（intent_node 的行为）
    assert len(human_msgs) == num_turns + 1, (
        f"持久化 state 应含全部 {num_turns + 1} 条 HumanMessage，"
        f"实际 {len(human_msgs)}"
    )
    assert len(ai_msgs) == num_turns + 1, (
        f"持久化 state 应含全部 {num_turns + 1} 条 AIMessage，"
        f"实际 {len(ai_msgs)}"
    )
    # 第 1 轮的 HumanMessage 仍应在持久化里（窗口不能误删底层数据）
    assert any("pturn0" in m.content for m in human_msgs), (
        "第 1 轮 pturn0 应仍在 SqliteSaver 持久化里，不被窗口删除"
    )