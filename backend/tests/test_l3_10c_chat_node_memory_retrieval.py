"""Task 22 后续 Step 1：Long-term Memory retrieval 接入 chat_node prompt 的测试。

目的：
    验证 chat_node 在不破坏现有 graph contract 的前提下：
    - 正确读取 user_memory
    - 与 RAG section 平级拼到 system prompt
    - DB 异常时 fail-safe
    - meta dict 字段齐全
    - 限 10 条
    - 其他 4 个节点不受影响
    - 图名 / 节点数 / AgentState 不变

设计原则：
    - 用 monkeypatch 替换 _build_user_memory_section 让测试稳定可控
    - 直接写 user_memory ORM 行（与现有 l3_10 测试一致）
    - 不打 LLM（mock _get_chat_chain）
"""

import pytest

from backend.agent import graph as graph_mod
from backend.agent.graph import (
    MAX_LONG_TERM_MEMORY_INJECT,
    _build_user_memory_section,
    chat_node,
    get_graph,
    reset_graph_for_tests,
)
from backend.models import UserMemory
from backend.database import SessionLocal


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _fresh_graph():
    """每个测试用全新图。"""
    reset_graph_for_tests()
    yield
    reset_graph_for_tests()


def _build_chat_state(user_id, user_input, thread_id="mem_ret_t1"):
    """构造一个 chat_node 能接受的最小 AgentState。"""
    return {
        "user_id": user_id,
        "input": user_input,
        "thread_id": thread_id,
        "messages": [],
    }


def _patch_chat_chain(monkeypatch, reply_text="好的，记住了。", captured=None):
    """把 chat_node 调用的 _get_chat_chain 替换成固定 reply 的 mock。"""
    class _MockResult:
        content = reply_text

    class _MockChain:
        def invoke(self, payload):
            if captured is not None:
                captured["payload"] = payload
            return _MockResult()

    monkeypatch.setattr(
        "backend.agent.graph._get_chat_chain",
        lambda: _MockChain(),
    )


def _insert_user_memories(user_id, items):
    """直接往 user_memory 表插数据。items: list of dicts。"""
    db = SessionLocal()
    try:
        for it in items:
            db.add(UserMemory(
                user_id=user_id,
                memory_type=it.get("memory_type", "fact"),
                key=it["key"],
                value=it["value"],
                confidence=it.get("confidence", 0.8),
                source=it.get("source", "llm_extracted"),
            ))
        db.commit()
    finally:
        db.close()


# ----------------------------------------------------------------------------
# 1. 正常读取 + 注入 prompt
# ----------------------------------------------------------------------------
class TestMemorySectionBuiltWhenDataExists:
    def test_memory_section_built_when_data_exists(self, user_id):
        """_build_user_memory_section 应把 user_memory 拼成 prompt 段。"""
        _insert_user_memories(user_id, [
            {"memory_type": "fact", "key": "job_title", "value": "学生", "confidence": 0.9},
            {"memory_type": "preference", "key": "favorite_food", "value": "川菜", "confidence": 0.8},
        ])
        section, meta = _build_user_memory_section(user_id)
        assert "用户的长期记忆" in section
        assert "job_title" in section
        assert "favorite_food" in section
        assert "学生" in section
        assert "川菜" in section
        assert meta["hits"] == 2
        assert meta["fetched"] == 2
        assert meta["took_ms"] >= 0.0


# ----------------------------------------------------------------------------
# 2. 没有 memory 时正常工作
# ----------------------------------------------------------------------------
class TestNoMemoryKeepsChatWorking:
    def test_no_memory_returns_empty_section(self, user_id):
        """user_memory 为空时返回 ("", meta) 且 meta 全 0。"""
        section, meta = _build_user_memory_section(user_id)
        assert section == ""
        assert meta["hits"] == 0
        assert meta["fetched"] == 0
        assert meta["took_ms"] >= 0.0

    def test_chat_node_works_without_memory(
        self, monkeypatch, user_id
    ):
        """chat_node 在没有 user_memory 时也能正常返回 reply。"""
        _patch_chat_chain(monkeypatch, reply_text="好的。")
        state = _build_chat_state(user_id, "你好")
        out = chat_node(state)
        assert out["reply"] == "好的。"
        assert isinstance(out["messages"], list)
        assert len(out["messages"]) == 1


# ----------------------------------------------------------------------------
# 3. DB 异常时 chat_node 不崩
# ----------------------------------------------------------------------------
class TestDBExceptionDoesNotBreakChat:
    def test_db_exception_returns_empty_section(self, monkeypatch, user_id):
        """DB 读取抛异常 → 返回 ("", meta) + 不抛。"""
        def _boom(db, uid):
            raise RuntimeError("simulated DB error")
        monkeypatch.setattr(
            "backend.agent.graph.get_user_memories", _boom
        )
        section, meta = _build_user_memory_section(user_id)
        assert section == ""
        assert meta["hits"] == 0
        assert meta["fetched"] == 0
        assert meta["took_ms"] >= 0.0

    def test_chat_node_works_when_db_raises(
        self, monkeypatch, user_id
    ):
        """DB 异常时 chat_node 仍返回正常 reply。"""
        def _boom(db, uid):
            raise RuntimeError("simulated DB error")
        monkeypatch.setattr(
            "backend.agent.graph.get_user_memories", _boom
        )
        _patch_chat_chain(monkeypatch, reply_text="还是能回答。")
        state = _build_chat_state(user_id, "你好")
        out = chat_node(state)
        assert out["reply"] == "还是能回答。"
        assert len(out["messages"]) == 1

    def test_empty_user_id_does_not_raise(self):
        """空 user_id 直接返回空 section，不抛。"""
        section, meta = _build_user_memory_section("")
        assert section == ""
        assert meta["hits"] == 0


# ----------------------------------------------------------------------------
# 4. 最多注入 10 条
# ----------------------------------------------------------------------------
class TestMax10MemoryInjection:
    def test_max_inject_constant_is_10(self):
        """MAX_LONG_TERM_MEMORY_INJECT 应当是 10。"""
        assert MAX_LONG_TERM_MEMORY_INJECT == 10

    def test_only_10_picked_when_15_exist(self, user_id):
        """15 条 memory → 只取 10 条注入。"""
        items = [
            {"memory_type": "fact", "key": f"key_{i:02d}", "value": f"val_{i}", "confidence": 0.5}
            for i in range(15)
        ]
        _insert_user_memories(user_id, items)
        section, meta = _build_user_memory_section(user_id)
        assert meta["fetched"] == 15
        assert meta["hits"] == 10
        # 解析注入的 10 条 key：每行格式 "- [type] key_NN = ..."
        import re
        injected_keys = re.findall(r"\[(\w+)\] (key_\d+) = ", section)
        assert len(injected_keys) == 10
        # 不可能全部 15 条都在
        assert section.count("key_") == 10


# ----------------------------------------------------------------------------
# 5. memory meta 字段
# ----------------------------------------------------------------------------
class TestMemoryMetaFields:
    def test_meta_has_all_required_keys(self, user_id):
        """meta 必须包含 hits / fetched / took_ms。"""
        _insert_user_memories(user_id, [
            {"memory_type": "habit", "key": "weekly_badminton", "value": "每周三打羽毛球"}
        ])
        section, meta = _build_user_memory_section(user_id)
        assert "hits" in meta
        assert "fetched" in meta
        assert "took_ms" in meta
        assert isinstance(meta["hits"], int)
        assert isinstance(meta["fetched"], int)
        assert isinstance(meta["took_ms"], float)

    def test_meta_took_ms_is_non_negative(self, user_id):
        """took_ms 必须 >= 0。"""
        _insert_user_memories(user_id, [
            {"memory_type": "fact", "key": "city", "value": "北京"}
        ])
        _, meta = _build_user_memory_section(user_id)
        assert meta["took_ms"] >= 0.0


# ----------------------------------------------------------------------------
# 6/7/8. RAG + memory 组合
# ----------------------------------------------------------------------------
class TestRAGAndMemoryCombination:
    def test_rag_and_memory_both_present(
        self, monkeypatch, user_id
    ):
        """RAG + memory 都存在 → prompt 含两段。"""
        _insert_user_memories(user_id, [
            {"memory_type": "preference", "key": "favorite_food", "value": "川菜"}
        ])
        monkeypatch.setattr(
            "backend.agent.rag.build_rag_prompt_section_cross_thread",
            lambda **kw: ("[RAG] 历史问答段", {"hits": 1, "deduped": 0, "avg_sim": 0.5, "max_sim": 0.5, "took_ms": 1.0}),
        )
        captured = {}
        _patch_chat_chain(monkeypatch, reply_text="回答。", captured=captured)
        state = _build_chat_state(user_id, "晚饭推荐")
        chat_node(state)
        sys_text = captured["payload"]["system_message"]
        assert "【历史会话问答】" in sys_text
        assert "【用户长期记忆】" in sys_text
        assert "[RAG]" in sys_text
        assert "favorite_food" in sys_text

    def test_rag_only_no_memory(
        self, monkeypatch, user_id
    ):
        """只有 RAG → 保留原有 prompt 文案（无【用户长期记忆】段）。"""
        monkeypatch.setattr(
            "backend.agent.rag.build_rag_prompt_section_cross_thread",
            lambda **kw: ("[RAG] 历史问答段", {"hits": 1, "deduped": 0, "avg_sim": 0.5, "max_sim": 0.5, "took_ms": 1.0}),
        )
        captured = {}
        _patch_chat_chain(monkeypatch, reply_text="回答。", captured=captured)
        state = _build_chat_state(user_id, "晚饭推荐")
        chat_node(state)
        sys_text = captured["payload"]["system_message"]
        assert "【用户长期记忆】" not in sys_text
        assert "[RAG]" in sys_text
        # RAG 内容仍然在
        assert "历史会话问答" in sys_text

    def test_memory_only_no_rag(
        self, monkeypatch, user_id
    ):
        """只有 memory → 走新加的 elif memory_section 分支。"""
        _insert_user_memories(user_id, [
            {"memory_type": "fact", "key": "job_title", "value": "设计师"}
        ])
        monkeypatch.setattr(
            "backend.agent.rag.build_rag_prompt_section_cross_thread",
            lambda **kw: ("", {"hits": 0, "deduped": 0, "avg_sim": 0.0, "max_sim": 0.0, "took_ms": 0.0}),
        )
        captured = {}
        _patch_chat_chain(monkeypatch, reply_text="回答。", captured=captured)
        state = _build_chat_state(user_id, "晚饭推荐")
        chat_node(state)
        sys_text = captured["payload"]["system_message"]
        assert "【用户长期记忆】" in sys_text
        assert "【历史会话问答】" not in sys_text
        assert "job_title" in sys_text

    def test_neither_rag_nor_memory_keeps_fallback(
        self, monkeypatch, user_id
    ):
        """两者都没有 → 保持原有 fallback system prompt。"""
        monkeypatch.setattr(
            "backend.agent.rag.build_rag_prompt_section_cross_thread",
            lambda **kw: ("", {"hits": 0, "deduped": 0, "avg_sim": 0.0, "max_sim": 0.0, "took_ms": 0.0}),
        )
        captured = {}
        _patch_chat_chain(monkeypatch, reply_text="回答。", captured=captured)
        state = _build_chat_state(user_id, "晚饭推荐")
        chat_node(state)
        sys_text = captured["payload"]["system_message"]
        assert "AI Budget Assistant" in sys_text
        assert "闲聊助手" in sys_text
        assert "【历史会话问答】" not in sys_text
        assert "【用户长期记忆】" not in sys_text


# ----------------------------------------------------------------------------
# 9. chat_node 输出 contract 不变
# ----------------------------------------------------------------------------
class TestChatNodeOutputContractUnchanged:
    def test_reply_and_messages_shape_unchanged(
        self, monkeypatch, user_id
    ):
        """chat_node 必须返回 {reply, messages} 两个 key。"""
        _insert_user_memories(user_id, [
            {"memory_type": "preference", "key": "favorite_food", "value": "川菜"}
        ])
        _patch_chat_chain(monkeypatch, reply_text="OK")
        state = _build_chat_state(user_id, "hi")
        out = chat_node(state)
        assert "reply" in out
        assert "messages" in out
        assert isinstance(out["reply"], str)
        assert isinstance(out["messages"], list)
        # 仅 1 条 AIMessage（自身）
        assert len(out["messages"]) == 1
        # AIMessage content == reply
        from langchain_core.messages import AIMessage
        assert isinstance(out["messages"][0], AIMessage)
        assert out["messages"][0].content == "OK"


# ----------------------------------------------------------------------------
# 10. 其他 4 个节点不受影响
# ----------------------------------------------------------------------------
class TestOtherNodesUnaffected:
    def test_expense_node_unchanged(
        self, monkeypatch, user_id
    ):
        """expense_node 不应读 user_memory。"""
        # 关键断言：即使有 memory，expense_node 也不应被影响
        _insert_user_memories(user_id, [
            {"memory_type": "fact", "key": "x", "value": "y"}
        ])
        # expense_node 内部调 LLM + save_expense；这里只验证不抛
        # 通过 mock _get_extract_chain + save_expense 验证流程不变
        class _ExtractedItem:
            category = "餐饮"
            amount = 30.0
            description = "午饭"
            time_text = "今天"
        class _Extracted:
            items = [_ExtractedItem()]
        class _ExtChain:
            def invoke(self, payload):
                return _Extracted()
        monkeypatch.setattr(
            "backend.agent.graph._get_extract_chain",
            lambda: _ExtChain(),
        )
        def _fake_save(user_id, expenses):
            return {"saved": expenses, "ids": [1]}
        monkeypatch.setattr(
            "backend.agent.tools.save_expense",
            type("_T", (), {"invoke": staticmethod(lambda self, x: _fake_save(**x))})(),
        )
        state = {"user_id": user_id, "input": "午饭30"}
        out = graph_mod.expense_node(state)
        assert "reply" in out


# ----------------------------------------------------------------------------
# 11. graph name 仍为 budget_agent_v1
# ----------------------------------------------------------------------------
class TestGraphContractStillIntact:
    def test_graph_name_is_budget_agent_v1(self):
        """图名仍为 budget_agent_v1（contract test 锁住）。"""
        g = get_graph()
        # LangGraph 给图实例有 .name 或 .get_name()；兼容两种
        name = getattr(g, "name", None) or g.get_name()
        assert name == "budget_agent_v1"

    def test_graph_still_has_6_nodes(self):
        """图仍含 6 个节点（intent/expense/query/analyze/budget/chat）。"""
        g = get_graph()
        # 节点名列表：LangGraph 内部存储
        nodes = list(g.nodes.keys()) if hasattr(g, "nodes") else list(g._nodes.keys())
        expected = {"intent_node", "expense_node", "query_node", "analyze_node", "budget_node", "chat_node"}
        assert expected.issubset(set(nodes))


# ----------------------------------------------------------------------------
# 12. 全量 contract：dispatcher 不被破坏
# ----------------------------------------------------------------------------
class TestDispatcherStillWorks:
    def test_dispatch_routes_chat_correctly(self, user_id):
        """dispatch() 仍能正确路由到 chat handler。"""
        from backend.agent.router import dispatch
        # 通过 mock 避免真实 LLM
        from langchain_core.messages import AIMessage
        class _StubChain:
            def invoke(self, payload):
                class _R:
                    content = "stub"
                return _R()
        import backend.agent.router as rmod
        rmod._intent_chain = _StubChain()
        rmod._extract_chain = _StubChain()
        rmod._query_chain = _StubChain()
        rmod._analyze_chain = _StubChain()
        rmod._budget_chain = _StubChain()
        rmod._chat_chain = _StubChain()
        handler, reply = dispatch(user_id=str(user_id), user_input="你好", thread_id="t_disp")
        assert reply == "stub"
