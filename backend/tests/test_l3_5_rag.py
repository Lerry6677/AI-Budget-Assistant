"""L3-5 RAG 雏形测试（TF-IDF + cosine）。

覆盖：
    1. rag.save_chat / retrieve_similar 单元
    2. rag.build_rag_prompt_section 拼接
    3. 用户隔离（A 看不到 B）
    4. 跨 thread 隔离（同用户不同 thread 也隔离）
    5. chat_node 接 RAG：写历史 + prompt 注入
    6. 集成：连续多轮 chat 第二次能召回第一次
"""

import pytest

from backend.agent import graph as graph_mod
from backend.agent import rag


# =============================================================================
# 1) save / retrieve
# =============================================================================
class TestRagSaveAndRetrieve:
    def test_save_chat_returns_id(self, user_id):
        rid = rag.save_chat(user_id, "t1", "我今天花了多少？", "一共 100 元。")
        assert rid > 0

    def test_retrieve_similar_basic(self, user_id):
        rag.save_chat(user_id, "t1", "我今天花了多少？", "一共 100 元。")
        rag.save_chat(user_id, "t1", "本月餐饮呢？", "餐饮 200 元。")
        rag.save_chat(user_id, "t1", "我喜欢喝咖啡", "好的，记住了。")

        # 相似查询 → 应召回
        hits = rag.retrieve_similar(
            user_id=user_id, thread_id="t1", query="今天花了多少", top_k=2
        )
        assert len(hits) >= 1
        # 命中第一条应该是"我今天花了多少？"
        assert "花了多少" in hits[0]["user_input"]

    def test_retrieve_similar_no_history(self, user_id):
        hits = rag.retrieve_similar(
            user_id=user_id, thread_id="nonexistent", query="随便问"
        )
        assert hits == []

    def test_retrieve_similar_filters_low_similarity(self, user_id):
        rag.save_chat(user_id, "t1", "我喜欢喝咖啡", "好的记住了")
        # 一个跟咖啡毫无关系的查询
        hits = rag.retrieve_similar(
            user_id=user_id, thread_id="t1", query="我今天搭乘出租车去机场", top_k=3,
            min_similarity=0.5,
        )
        # min_similarity=0.5 严格，应过滤掉
        assert hits == []


# =============================================================================
# 2) build_rag_prompt_section
# =============================================================================
class TestBuildRagPromptSection:
    def test_empty_history_returns_empty_string(self, user_id):
        section = rag.build_rag_prompt_section(
            user_id=user_id, thread_id="empty", query="随便"
        )
        assert section == ""

    def test_with_history_returns_xml_section(self, user_id):
        rag.save_chat(user_id, "t1", "你叫什么？", "我叫小助。")
        rag.save_chat(user_id, "t1", "我住哪里？", "你住北京。")

        section = rag.build_rag_prompt_section(
            user_id=user_id, thread_id="t1", query="你叫什么名字", top_k=2
        )
        assert "<history>" in section
        assert "</history>" in section
        assert "[用户]" in section
        assert "[回答]" in section

    def test_top_k_limit(self, user_id):
        for i in range(5):
            rag.save_chat(user_id, "tk", f"问题{i}", f"回答{i}")
        section = rag.build_rag_prompt_section(
            user_id=user_id, thread_id="tk", query="问题", top_k=2
        )
        # 2 条 → 2 个 [用户]
        assert section.count("[用户]") == 2


# =============================================================================
# 3) 用户隔离
# =============================================================================
class TestRagUserIsolation:
    def test_user_b_cannot_see_user_a(self, user_id, other_user_id):
        """A 写的问题，B 检索时不应召回。"""
        rag.save_chat(user_id, "iso_t", "我月薪 5 万", "好的记住了")
        hits = rag.retrieve_similar(
            user_id=other_user_id, thread_id="iso_t",
            query="我月薪", top_k=3,
        )
        assert all(h["user_input"] != "我月薪 5 万" for h in hits)

    def test_same_user_different_thread_isolated(self, user_id):
        """同用户但 thread 不同，检索不串。"""
        rag.save_chat(user_id, "thread_A", "A 的秘密", "A 的回答")
        rag.save_chat(user_id, "thread_B", "B 的秘密", "B 的回答")

        hits_a = rag.retrieve_similar(
            user_id=user_id, thread_id="thread_A", query="秘密", top_k=3
        )
        assert all(h["user_input"] == "A 的秘密" for h in hits_a)
        hits_b = rag.retrieve_similar(
            user_id=user_id, thread_id="thread_B", query="秘密", top_k=3
        )
        assert all(h["user_input"] == "B 的秘密" for h in hits_b)


# =============================================================================
# 4) chat_node 集成 RAG
# =============================================================================
class TestChatNodeRagIntegration:
    def test_chat_node_writes_history(self, monkeypatch, user_id):
        """chat_node 完成后应写 chat_history。"""
        from langgraph.checkpoint.memory import InMemorySaver

        # Mock chat chain：返回一个带 .invoke(payload) 的对象
        # agent_reply 用与 query 重叠的关键词（"测试"），确保 TF-IDF 召回
        class _MockResult:
            content = "你叫测试名。"

        class _MockChain:
            def invoke(self, payload):
                return _MockResult()

        monkeypatch.setattr(
            "backend.agent.graph._get_chat_chain",
            lambda: _MockChain(),
        )

        compiled = graph_mod._build_graph(checkpointer=InMemorySaver())
        compiled.invoke(
            {
                "user_id": user_id,
                "input": "我的测试名叫啥？",
                "thread_id": "rag_int_t1",
            },
            config={"configurable": {"thread_id": "rag_int_t1"}},
        )
        # 验证写库
        hits = rag.retrieve_similar(
            user_id=user_id, thread_id="rag_int_t1", query="我的测试名叫啥", top_k=3
        )
        assert any(h["user_input"] == "我的测试名叫啥？" for h in hits)
        assert any(h["agent_reply"] == "你叫测试名。" for h in hits)

    def test_chat_node_injects_history_into_prompt(
        self, monkeypatch, user_id
    ):
        """chat_node 第二次调用时，chain 应被注入 RAG system。

        L3-6 升级后：chat_node 召回的是"其他 thread"的历史（exclude 当前 thread），
        所以 seed 数据要放在**另一个** thread 才能召回。
        """
        from langgraph.checkpoint.memory import InMemorySaver

        captured = {"system_message": None}

        class _MockChain:
            def invoke(self, payload):
                captured["system_message"] = payload.get("system_message", "")
                class _R:
                    content = "ok"
                return _R()

        monkeypatch.setattr(
            "backend.agent.graph._get_chat_chain",
            lambda: _MockChain(),
        )

        # seed 数据放在**另一个** thread，让当前 thread 的检索能跨 thread 召回
        rag.save_chat(user_id, "rag_prompt_t_seed", "我的薪酬多少", "你的薪酬是 5 万")

        compiled = graph_mod._build_graph(checkpointer=InMemorySaver())
        compiled.invoke(
            {"user_id": user_id, "input": "我的薪酬多少？", "thread_id": "rag_prompt_t"},
            config={"configurable": {"thread_id": "rag_prompt_t"}},
        )
        # system_message 应该是 RAG 段
        sys_msg = captured["system_message"]
        assert sys_msg is not None
        assert "历史问答" in sys_msg or "<history" in sys_msg

    def test_chat_node_no_history_uses_default_system(
        self, monkeypatch, user_id
    ):
        """无历史时，system 用默认闲聊，不应包含 <history>。"""
        from langgraph.checkpoint.memory import InMemorySaver

        captured = {"system_message": None}

        class _MockChain:
            def invoke(self, payload):
                captured["system_message"] = payload.get("system_message", "")
                class _R:
                    content = "ok"
                return _R()

        monkeypatch.setattr(
            "backend.agent.graph._get_chat_chain",
            lambda: _MockChain(),
        )

        compiled = graph_mod._build_graph(checkpointer=InMemorySaver())
        compiled.invoke(
            {"user_id": user_id, "input": "你好", "thread_id": "no_hist_t"},
            config={"configurable": {"thread_id": "no_hist_t"}},
        )
        sys_msg = captured["system_message"]
        assert "<history>" not in sys_msg
        assert "闲聊助手" in sys_msg
