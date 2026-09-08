"""阶段 2-1：thread_id 用户级隔离。

背景（漏洞）：
    thread_id 是 LangGraph checkpointer 的唯一分区键
    （graph.run_agent 里 config={"configurable": {"thread_id": ...}}），而
    AgentState.messages 是 add_messages 累加型字段。前端 Chat 页硬编码
    thread_id="main"、统计页硬编码 "local:stats"，旧实现 _chat_with_agent 直接
    `tid = thread_id or f"user_{user_id}"` 透传，导致**所有用户共用同一个
    checkpoint 线程**：chat_node 拼给 LLM 的 history 里会混入别人的对话。
    （实证：backend/checkpoints.sqlite 的 thread 'main' 里存在 user_id 2/3/4
      的写入；MySQL chat_history 里 thread_id='main' 被 2 个不同 user_id 共用。）

修复：
    backend/api/chat.py::build_scoped_thread_id 把前端传来的值降级为
    "会话空间名"，再用 JWT 的 user_id 做命名空间：
        普通会话   -> f"{user_id}:{conversation_id}"      例 "26:main"
        local 会话 -> f"local:{user_id}:{rest}"           例 "local:26:stats"
    /chat 写入端与 /chat/history 读取端使用同一套规则。

本文件覆盖：
    Case 1  同一用户、同一 thread 可以读取自己的历史状态
    Case 2  不同用户即使用相同 conversation_id，最终 thread_id 也必须不同
    Case 3  不能通过前端伪造 user_id / thread_id 越权
    Case 4  /chat/history 只返回当前 JWT 用户的数据
    兼容性  "local:" 前缀契约（graph._persist_history 跳过落库）不被破坏

所有 LLM 依赖通过 monkeypatch 替换；不发起真实网络请求。
"""

from __future__ import annotations

import pytest

from backend.agent import graph as graph_mod
from backend.agent.prompts import IntentResult
from backend.api.chat import build_scoped_thread_id
from backend.api.dependencies import get_current_user


# ----------------------------------------------------------------------------
# 共用 fixtures
# ----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    """工具走 DRY_RUN，不写真实账单；rag.save_chat 静默，避免依赖 RAG 库。"""
    monkeypatch.setattr("backend.agent.tools.DRY_RUN", True)
    monkeypatch.setattr("backend.agent.rag.save_chat", lambda *a, **kw: -1)


@pytest.fixture
def agent_enabled(monkeypatch):
    """强制走 LangGraph 分支，不依赖 .env 里的 AGENT_ENABLED。"""
    monkeypatch.setattr("backend.api.chat.AGENT_ENABLED", True)


@pytest.fixture
def login(client):
    """返回工厂：把 get_current_user 覆盖成指定 id 的假用户（模拟 JWT 已通过）。"""

    def _login(uid):
        client.app.dependency_overrides[get_current_user] = lambda: type(
            "U", (), {"id": uid, "username": f"tester_{uid}"}
        )()
        return uid

    yield _login
    client.app.dependency_overrides.clear()


@pytest.fixture
def dispatch_calls(monkeypatch):
    """拦截 backend.api.chat.dispatch，记录真正交给 LangGraph 的参数。

    这是本文件的核心探针：thread_id 隔离是否生效，取决于最终传给 dispatch
    （进而传给 run_agent 的 configurable.thread_id）的是什么值。
    """
    calls: list[dict] = []

    def _fake_dispatch(user_id, user_input, thread_id=None):
        calls.append(
            {"user_id": user_id, "user_input": user_input, "thread_id": thread_id}
        )
        return ("chat", "ok")

    monkeypatch.setattr("backend.api.chat.dispatch", _fake_dispatch)
    return calls


@pytest.fixture
def fresh_graph(monkeypatch):
    """独立的 InMemorySaver checkpointer（与 test_l3_8 同一套做法），测试间互不干扰。"""
    from langgraph.checkpoint.memory import InMemorySaver

    # 长期记忆抽取是 daemon 线程旁路，测试里关掉，避免线程异常噪音
    monkeypatch.setattr(
        "backend.agent.graph._dispatch_memory_extraction", lambda *a, **kw: None
    )
    return graph_mod._build_graph(checkpointer=InMemorySaver())


@pytest.fixture
def chat_chain_calls(monkeypatch):
    """Mock chat chain：记录每次 invoke 的 kwargs（尤其是 history），返回固定回复。"""
    calls: list[dict] = []

    class _FakeResult:
        def __init__(self, content: str):
            self.content = content

    def _invoke(kwargs):
        calls.append(kwargs)
        return _FakeResult("pong")

    chain = type("C", (), {"invoke": staticmethod(_invoke)})()
    monkeypatch.setattr("backend.agent.graph._get_chat_chain", lambda: chain)
    return calls


@pytest.fixture
def intent_chat(monkeypatch):
    """强制所有输入都走 chat 意图（只有 chat_node 会消费 messages 短期记忆）。"""
    monkeypatch.setattr(
        "backend.agent.graph.classify_intent",
        lambda user_input: IntentResult(category="chat", confidence=0.99, reason="闲聊"),
    )


def _invoke(graph, uid: str, text: str, tid: str):
    """按 run_agent 的方式跑一次图（thread_id 同时进 state 和 configurable）。"""
    return graph.invoke(
        {"user_id": str(uid), "input": text, "thread_id": tid},
        config={"configurable": {"thread_id": tid}},
    )


def _history_texts(kwargs: dict) -> list[str]:
    return [m.content for m in (kwargs.get("history") or [])]


def _seed_history(uid: str, thread_id: str, question: str, answer: str) -> None:
    from backend.database import SessionLocal
    from backend.models import ChatHistory

    db = SessionLocal()
    try:
        db.add(
            ChatHistory(
                user_id=str(uid),
                thread_id=thread_id,
                user_input=question,
                agent_reply=answer,
            )
        )
        db.commit()
    finally:
        db.close()


# ============================================================================
# 0. build_scoped_thread_id 纯函数契约
# ============================================================================
class TestBuildScopedThreadId:
    def test_format_is_user_scoped(self):
        assert build_scoped_thread_id(26, "main") == "26:main"

    @pytest.mark.parametrize("conv", [None, "", "   "])
    def test_defaults_to_main(self, conv):
        """缺省 / 空串 / 纯空白都落到默认会话，且仍然带用户前缀。"""
        assert build_scoped_thread_id(26, conv) == "26:main"

    def test_local_prefix_kept_at_front(self):
        """关键兼容性：'local:' 必须留在最前面，否则 _persist_history 不再跳过落库。"""
        scoped = build_scoped_thread_id(26, "local:stats")
        assert scoped == "local:26:stats"
        assert scoped.startswith("local:")

    def test_local_prefix_without_rest_falls_back(self):
        assert build_scoped_thread_id(26, "local:") == "local:26:main"

    def test_int_and_str_user_id_agree(self):
        assert build_scoped_thread_id(26, "main") == build_scoped_thread_id("26", "main")

    def test_fits_chat_history_column(self):
        """ChatHistory.thread_id 是 String(100)，最坏情况也不能溢出。"""
        worst = build_scoped_thread_id(1234567890, "a" * 64)
        assert len(worst) <= 100, f"scoped thread_id 过长: {len(worst)}"
        worst_local = build_scoped_thread_id(1234567890, "local:" + "a" * 58)
        assert len(worst_local) <= 100, f"scoped local thread_id 过长: {len(worst_local)}"


# ============================================================================
# Case 2：不同用户 + 相同 conversation_id → thread_id 必须不同
# ============================================================================
class TestCase2DifferentUsers:
    def test_same_conversation_different_users_get_different_threads(
        self, client, agent_enabled, login, dispatch_calls, user_id, other_user_id
    ):
        login(user_id)
        r1 = client.post("/chat", json={"message": "你好", "thread_id": "main"})
        assert r1.status_code == 200, r1.text

        login(other_user_id)
        r2 = client.post("/chat", json={"message": "你好", "thread_id": "main"})
        assert r2.status_code == 200, r2.text

        tid_a, tid_b = dispatch_calls[0]["thread_id"], dispatch_calls[1]["thread_id"]
        assert tid_a != tid_b, f"两个用户使用相同 conversation_id 却得到相同 thread_id: {tid_a}"
        assert tid_a == f"{user_id}:main"
        assert tid_b == f"{other_user_id}:main"

    def test_hardcoded_shared_thread_ids_never_reach_graph(
        self, client, agent_enabled, login, dispatch_calls, user_id, other_user_id
    ):
        """回归护栏：前端硬编码的 "main" / "local:stats" 不得原样成为 checkpoint 键。"""
        for uid in (user_id, other_user_id):
            login(uid)
            for conv in ("main", "local:stats"):
                resp = client.post("/chat", json={"message": "hi", "thread_id": conv})
                assert resp.status_code == 200, resp.text

        reached = [c["thread_id"] for c in dispatch_calls]
        assert "main" not in reached, f"共享 thread_id 'main' 仍然直达 LangGraph: {reached}"
        assert "local:stats" not in reached, (
            f"共享 thread_id 'local:stats' 仍然直达 LangGraph: {reached}"
        )
        for tid in reached:
            assert str(user_id) in tid or str(other_user_id) in tid, (
                f"thread_id 未包含 JWT 用户标识: {tid}"
            )

    def test_local_stats_isolated_between_users(
        self, client, agent_enabled, login, dispatch_calls, user_id, other_user_id
    ):
        login(user_id)
        client.post("/chat", json={"message": "hi", "thread_id": "local:stats"})
        login(other_user_id)
        client.post("/chat", json={"message": "hi", "thread_id": "local:stats"})

        tid_a, tid_b = dispatch_calls[0]["thread_id"], dispatch_calls[1]["thread_id"]
        assert tid_a != tid_b
        assert tid_a.startswith("local:") and tid_b.startswith("local:")

    def test_checkpoint_state_isolated_between_users(
        self, fresh_graph, chat_chain_calls, intent_chat, user_id, other_user_id
    ):
        """最强证明：两个用户用同一 conversation_id，彼此看不到对方的 checkpoint 记忆。"""
        tid_a = build_scoped_thread_id(user_id, "main")
        tid_b = build_scoped_thread_id(other_user_id, "main")
        assert tid_a != tid_b

        _invoke(fresh_graph, user_id, "我喜欢喝咖啡", tid_a)
        _invoke(fresh_graph, other_user_id, "我喜欢喝茶", tid_b)

        b_history = _history_texts(chat_chain_calls[1])
        assert not any("咖啡" in c for c in b_history), (
            f"用户 B 的 LLM history 泄漏了用户 A 的对话: {b_history}"
        )

        # A 再问一轮，自己的记忆仍然在
        _invoke(fresh_graph, user_id, "我最近喜欢喝什么", tid_a)
        a_history = _history_texts(chat_chain_calls[2])
        assert any("咖啡" in c for c in a_history), (
            f"用户 A 丢失了自己的历史: {a_history}"
        )
        assert not any("茶" in c for c in a_history), (
            f"用户 A 的 history 混入了用户 B 的对话: {a_history}"
        )

    def test_unscoped_shared_thread_would_leak_control(
        self, fresh_graph, chat_chain_calls, intent_chat, user_id, other_user_id
    ):
        """对照实验：不做 scope、两人共用 "main" 时确实会串台。

        这条测试锁定"为什么必须隔离"。若有人回退 build_scoped_thread_id，
        上面 test_checkpoint_state_isolated_between_users 会失败，而这条会通过，
        两者对照即可立刻定位是隔离被破坏，而不是图本身坏了。
        """
        _invoke(fresh_graph, user_id, "我喜欢喝咖啡", "main")
        _invoke(fresh_graph, other_user_id, "我喜欢喝茶", "main")

        b_history = _history_texts(chat_chain_calls[1])
        assert any("咖啡" in c for c in b_history), (
            "对照实验失效：共用 thread 时本应发生串台，请检查测试前置条件"
        )


# ============================================================================
# Case 1：同一用户、同一 thread 可以读取自己的历史状态
# ============================================================================
class TestCase1SameUserSameThread:
    def test_thread_id_is_stable_across_requests(
        self, client, agent_enabled, login, dispatch_calls, user_id
    ):
        login(user_id)
        for _ in range(3):
            resp = client.post("/chat", json={"message": "hi", "thread_id": "main"})
            assert resp.status_code == 200, resp.text

        tids = {c["thread_id"] for c in dispatch_calls}
        assert len(tids) == 1, f"同一用户同一会话应得到稳定 thread_id，实际 {tids}"
        assert tids == {f"{user_id}:main"}

    def test_omitted_thread_id_matches_explicit_main(
        self, client, agent_enabled, login, dispatch_calls, user_id
    ):
        """前端不传 thread_id 与显式传 "main" 必须落到同一个会话，否则刷新后历史对不上。"""
        login(user_id)
        client.post("/chat", json={"message": "hi"})
        client.post("/chat", json={"message": "hi", "thread_id": "main"})

        assert dispatch_calls[0]["thread_id"] == dispatch_calls[1]["thread_id"]
        assert dispatch_calls[0]["thread_id"] == f"{user_id}:main"

    def test_same_user_reads_own_checkpoint_state(
        self, fresh_graph, chat_chain_calls, intent_chat, user_id
    ):
        tid = build_scoped_thread_id(user_id, "main")
        _invoke(fresh_graph, user_id, "我喜欢喝咖啡", tid)
        _invoke(fresh_graph, user_id, "我最近喜欢喝什么", tid)

        second = _history_texts(chat_chain_calls[1])
        assert any("咖啡" in c for c in second), (
            f"同一用户同一 thread 应能读回自己的历史，实际 {second}"
        )


# ============================================================================
# Case 3：不能通过前端伪造 user_id / thread_id 越权
# ============================================================================
class TestCase3NoSpoofing:
    def test_forged_user_id_in_body_is_ignored(
        self, client, agent_enabled, login, dispatch_calls, user_id, other_user_id
    ):
        """JWT user_id = A，请求体伪造 user_id = B → 必须以 JWT 为准。"""
        login(user_id)
        resp = client.post(
            "/chat",
            json={
                "message": "hi",
                "thread_id": "main",
                "user_id": other_user_id,  # 伪造字段
            },
        )
        assert resp.status_code == 200, resp.text

        call = dispatch_calls[0]
        assert call["user_id"] == str(user_id), (
            f"dispatch 收到伪造的 user_id: {call['user_id']}"
        )
        assert call["thread_id"] == f"{user_id}:main"
        assert str(other_user_id) not in call["thread_id"], (
            f"伪造的 user_id 渗入了 thread_id: {call['thread_id']}"
        )

    def test_forged_thread_id_cannot_reach_other_user_namespace(
        self, client, agent_enabled, login, dispatch_calls, user_id, other_user_id
    ):
        """A 直接提交 B 的 scoped thread_id，也不能命中 B 的命名空间。"""
        victim_tid = build_scoped_thread_id(other_user_id, "main")

        login(user_id)
        resp = client.post("/chat", json={"message": "hi", "thread_id": victim_tid})
        assert resp.status_code == 200, resp.text

        reached = dispatch_calls[0]["thread_id"]
        assert reached != victim_tid, "A 成功使用了 B 的 thread_id"
        assert reached.startswith(f"{user_id}:"), (
            f"thread_id 未以 JWT 用户命名空间开头: {reached}"
        )

    def test_forged_query_user_id_on_history_is_ignored(
        self, client, login, user_id, other_user_id
    ):
        """/chat/history 上伪造 user_id 查询参数无效（该端点根本不读它）。"""
        _seed_history(
            other_user_id,
            build_scoped_thread_id(other_user_id, "main"),
            "B的私密问题",
            "B的私密回复",
        )
        login(user_id)
        resp = client.get(
            "/chat/history", params={"user_id": other_user_id, "thread_id": "main"}
        )
        assert resp.status_code == 200, resp.text
        assert "B的私密" not in resp.text


# ============================================================================
# Case 4：/chat/history 只属于当前 JWT 用户
# ============================================================================
class TestCase4HistoryIsolation:
    def test_history_returns_only_own_rows(
        self, client, login, user_id, other_user_id
    ):
        _seed_history(
            user_id, build_scoped_thread_id(user_id, "main"), "A的问题", "A的回复"
        )
        _seed_history(
            other_user_id,
            build_scoped_thread_id(other_user_id, "main"),
            "B的问题",
            "B的回复",
        )

        login(user_id)
        resp = client.get("/chat/history", params={"thread_id": "main"})
        assert resp.status_code == 200, resp.text

        body = resp.json()
        contents = [m["content"] for m in body]
        assert "A的问题" in contents and "A的回复" in contents
        assert not any("B的" in c for c in contents), f"越权读到别人的历史: {contents}"

    def test_history_cannot_read_other_user_by_forging_thread_id(
        self, client, login, user_id, other_user_id
    ):
        _seed_history(
            other_user_id,
            build_scoped_thread_id(other_user_id, "main"),
            "B的问题",
            "B的回复",
        )

        login(user_id)
        resp = client.get(
            "/chat/history",
            params={"thread_id": build_scoped_thread_id(other_user_id, "main")},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == [], "用伪造 thread_id 竟然读到了数据"

    def test_history_without_thread_id_still_user_scoped(
        self, client, login, user_id, other_user_id
    ):
        """不传 thread_id 时行为不变（返回该用户所有会话），但绝不跨用户。"""
        _seed_history(user_id, build_scoped_thread_id(user_id, "main"), "A主会话", "a1")
        _seed_history(user_id, build_scoped_thread_id(user_id, "trip"), "A其他会话", "a2")
        _seed_history(other_user_id, build_scoped_thread_id(other_user_id, "main"), "B主会话", "b1")

        login(user_id)
        contents = [m["content"] for m in client.get("/chat/history").json()]
        assert "A主会话" in contents and "A其他会话" in contents
        assert "B主会话" not in contents, f"不传 thread_id 时跨用户泄漏: {contents}"

    def test_history_read_path_matches_chat_write_path(
        self, client, agent_enabled, login, monkeypatch, user_id
    ):
        """读写两端必须用同一套 scope 规则，否则 /chat 写进去的历史 /chat/history 读不出来。

        做法：拦下 dispatch 拿到 /chat 实际使用的 thread_id，按 graph._persist_history
        的效果把同一 thread_id 的问答对落库，再用 thread_id="main" 查 /chat/history，
        断言能读回。（不走 rag.save_chat，避开 autouse fixture 已把它换成 no-op。）
        """
        written: list[str] = []

        def _fake_dispatch(user_id, user_input, thread_id=None):
            # 注：形参名必须是 user_id —— _chat_with_agent 用关键字传参
            written.append(thread_id)
            _seed_history(user_id, thread_id, user_input, "pong")
            return ("chat", "pong")

        monkeypatch.setattr("backend.api.chat.dispatch", _fake_dispatch)

        login(user_id)
        resp = client.post("/chat", json={"message": "我喜欢喝咖啡", "thread_id": "main"})
        assert resp.status_code == 200, resp.text
        assert written == [f"{user_id}:main"], f"/chat 写入的 thread_id 异常: {written}"

        hist = client.get("/chat/history", params={"thread_id": "main"})
        assert hist.status_code == 200, hist.text
        contents = [m["content"] for m in hist.json()]
        assert "我喜欢喝咖啡" in contents, (
            f"写入 thread_id={written[0]} 但读取端对不上，返回 {contents}"
        )

    def test_history_still_rejects_invalid_thread_id(self, client, login, user_id):
        """scope 之前仍先做白名单校验，原有 400 行为不被破坏。"""
        login(user_id)
        resp = client.get("/chat/history", params={"thread_id": "bad$id"})
        assert resp.status_code == 400, resp.text


# ============================================================================
# 兼容性：local: 前缀契约（graph._persist_history 跳过落库）
# ============================================================================
class TestLocalPrefixContractPreserved:
    def test_scoped_local_thread_still_skips_persist_history(
        self, monkeypatch, user_id
    ):
        """scope 之后仍然以 "local:" 开头 → _persist_history 必须继续跳过写库。

        这是"统计页不污染 chat_history"的既有功能，隔离改造不能把它弄坏。
        """
        calls: list[dict] = []

        def _record(uid, tid, user_input, reply):
            calls.append({"user_id": uid, "thread_id": tid})
            return 1

        monkeypatch.setattr("backend.agent.rag.save_chat", _record)

        scoped = build_scoped_thread_id(user_id, "local:stats")
        graph_mod._persist_history(
            {"user_id": str(user_id), "thread_id": scoped, "input": "x"}, "x", "y"
        )
        assert calls == [], f"scoped local thread 不应写 chat_history，实际 {calls}"

    def test_scoped_normal_thread_still_persists_history(self, monkeypatch, user_id):
        """反向确认：普通会话 scope 之后仍然正常落库（没有被误判成 local）。"""
        calls: list[dict] = []

        def _record(uid, tid, user_input, reply):
            calls.append({"user_id": uid, "thread_id": tid})
            return 1

        monkeypatch.setattr("backend.agent.rag.save_chat", _record)

        scoped = build_scoped_thread_id(user_id, "main")
        graph_mod._persist_history(
            {"user_id": str(user_id), "thread_id": scoped, "input": "x"}, "x", "y"
        )
        assert len(calls) == 1, f"普通会话应写 chat_history，实际 {calls}"
        assert calls[0]["thread_id"] == scoped
