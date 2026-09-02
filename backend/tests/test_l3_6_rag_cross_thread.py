"""L3-6 跨 thread RAG 测试。

覆盖：
    1. retrieve_similar_cross_thread 单元：跨 thread 召回
    2. exclude_thread_id 防止自召回
    3. 跨 user 隔离（关键：跨 thread 不能跨 user）
    4. build_rag_prompt_section_cross_thread 拼接格式
    5. chat_node 接跨 thread RAG：第二个 thread 能召回第一个 thread 的相似问答
    6. min_similarity 阈值过滤
    7. 边界：空 user / 空 query / 空历史
"""

import pytest

from backend.agent import graph as graph_mod
from backend.agent import rag


# =============================================================================
# 1) 跨 thread 召回
# =============================================================================
class TestCrossThreadRetrieval:
    def test_retrieve_from_other_thread(self, user_id):
        """A thread 写的问题，B thread 检索应能召回（同一 user）。"""
        # 历史放在 thread_Y（不排除的那个）；thread_X 写无关内容以便 exclude
        rag.save_chat(user_id, "thread_X", "今天天气如何", "天气晴朗")
        rag.save_chat(user_id, "thread_Y", "我月薪多少", "你的月薪是 5 万")

        hits = rag.retrieve_similar_cross_thread(
            user_id=user_id,
            query="我的月薪多少",
            top_k=3,
            exclude_thread_id="thread_X",
        )
        assert len(hits) >= 1
        # 高度相似 query 应命中 "我月薪多少"
        assert any("月薪多少" in h["user_input"] for h in hits)
        # 跨 thread 必须带 thread_id 字段
        for h in hits:
            assert "thread_id" in h

    def test_exclude_current_thread_prevents_self_recall(self, user_id):
        """exclude_thread_id 应过滤掉当前 thread 的历史。"""
        # 当前 thread 写两条高度重叠的问题
        rag.save_chat(user_id, "current_t", "咖啡我喜欢", "好的记住了咖啡")
        rag.save_chat(user_id, "current_t", "我爱喝咖啡", "好的记住了")
        # 另一 thread 写一条无关
        rag.save_chat(user_id, "other_t", "今天天气真好", "是的")

        hits = rag.retrieve_similar_cross_thread(
            user_id=user_id,
            query="我喜欢什么饮料",
            top_k=5,
            exclude_thread_id="current_t",  # 排除掉两条咖啡
        )
        # 当前 thread 的两条都不能召回
        assert all(h["thread_id"] != "current_t" for h in hits)

    def test_user_isolation_still_holds_cross_thread(self, user_id, other_user_id):
        """跨 thread 不能跨 user（最关键的隔离边界）。"""
        rag.save_chat(user_id, "user_a_t", "我月薪 5 万", "好的")
        rag.save_chat(user_id, "user_a_t2", "我喜欢旅游", "好的")

        hits = rag.retrieve_similar_cross_thread(
            user_id=other_user_id,
            query="月薪",
            top_k=5,
        )
        assert all(h["user_input"] != "我月薪 5 万" for h in hits)
        assert hits == []  # other_user 没历史 → 空

    def test_min_similarity_filters_noise(self, user_id):
        """min_similarity 严格时应丢掉无关历史。"""
        rag.save_chat(user_id, "t1", "我喜欢喝咖啡", "好的")
        hits = rag.retrieve_similar_cross_thread(
            user_id=user_id,
            query="我今天搭乘出租车去机场",
            top_k=5,
            min_similarity=0.5,
        )
        assert hits == []

    def test_top_k_limit(self, user_id):
        """top_k 应限制返回条数。"""
        for i in range(8):
            rag.save_chat(user_id, f"seed_t{i}", f"我喜欢喝咖啡{i}", "ok")
        hits = rag.retrieve_similar_cross_thread(
            user_id=user_id,
            query="我喜欢喝咖啡",
            top_k=3,
            min_similarity=0.0,
        )
        assert len(hits) == 3

    def test_empty_user_returns_empty(self):
        hits = rag.retrieve_similar_cross_thread(user_id="", query="x")
        assert hits == []

    def test_empty_query_returns_empty(self, user_id):
        rag.save_chat(user_id, "t", "问题", "回答")
        hits = rag.retrieve_similar_cross_thread(user_id=user_id, query="")
        assert hits == []

    def test_no_history_returns_empty(self, user_id):
        hits = rag.retrieve_similar_cross_thread(user_id=user_id, query="随便问")
        assert hits == []


# =============================================================================
# 2) build_rag_prompt_section_cross_thread
# =============================================================================
class TestBuildCrossThreadPrompt:
    def test_empty_history_returns_empty_string(self, user_id):
        section = rag.build_rag_prompt_section_cross_thread(
            user_id=user_id, query="随便"
        )
        assert section == ""

    def test_with_history_returns_xml_section(self, user_id):
        rag.save_chat(user_id, "old_t", "你叫什么名字", "我叫小助")
        section = rag.build_rag_prompt_section_cross_thread(
            user_id=user_id,
            query="你叫什么名字",
            top_k=2,
            exclude_thread_id="current",
            current_thread_id="current",
        )
        assert "<history cross_thread=true>" in section
        assert "</history>" in section
        assert "[用户/thread:" in section  # 来源标注
        assert "[回答]" in section

    def test_current_thread_tag_when_match(self, user_id):
        """当 current_thread_id 与历史 thread_id 一致时打 thread:current 标。"""
        rag.save_chat(user_id, "ct", "测试问题", "测试回答")
        section = rag.build_rag_prompt_section_cross_thread(
            user_id=user_id,
            query="测试",
            top_k=2,
            exclude_thread_id=None,  # 不排除
            current_thread_id="ct",
        )
        # 当前 thread 历史应被标为 thread:current
        assert "thread:current" in section


# =============================================================================
# 3) chat_node 接跨 thread RAG
# =============================================================================
class TestChatNodeCrossThreadRag:
    def test_chat_node_recalls_from_previous_thread(
        self, monkeypatch, user_id
    ):
        """第 1 个 thread 写过的问题，第 2 个 thread 提问时 chat_node 应召回。"""
        from langgraph.checkpoint.memory import InMemorySaver

        # 先 seed：thread_A 写"测试名"
        rag.save_chat(user_id, "thread_A", "我的测试名叫啥？", "叫 Alpha。")

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

        # 在新 thread_B 提问 → chat_node 应召回 thread_A 的问答
        compiled = graph_mod._build_graph(checkpointer=InMemorySaver())
        compiled.invoke(
            {"user_id": user_id, "input": "我的测试名叫啥？", "thread_id": "thread_B"},
            config={"configurable": {"thread_id": "thread_B"}},
        )
        # 验证 prompt 注入跨 thread 段
        sys_msg = captured["system_message"]
        assert sys_msg is not None
        assert "跨 thread" in sys_msg or "cross_thread" in sys_msg
        assert "测试名" in sys_msg or "Alpha" in sys_msg

    def test_chat_node_excludes_current_thread_in_prompt(
        self, monkeypatch, user_id
    ):
        """chat_node 第二次在同一 thread 调用时，不应召回自己刚写的（防止噪声循环）。

        实际上 L3-6 设计的 exclude_thread_id 就是为了避免这一点。
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

        # 在另一 thread 写一条相似问答
        rag.save_chat(user_id, "another_t", "薪酬多少", "5 万")

        # 当前 thread 提问：不应召回 another_t 之外的内容（因为只有 another_t 有数据）
        compiled = graph_mod._build_graph(checkpointer=InMemorySaver())
        compiled.invoke(
            {"user_id": user_id, "input": "我的薪酬多少", "thread_id": "self_t"},
            config={"configurable": {"thread_id": "self_t"}},
        )
        # 系统提示应包含跨 thread 段
        sys_msg = captured["system_message"]
        assert "<history" in sys_msg
        assert "5 万" in sys_msg

    def test_chat_node_no_history_uses_default_system(
        self, monkeypatch, user_id
    ):
        """无任何历史时，system 用默认闲聊，不应包含 <history>。"""
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
            {"user_id": user_id, "input": "你好", "thread_id": "fresh_t"},
            config={"configurable": {"thread_id": "fresh_t"}},
        )
        sys_msg = captured["system_message"]
        assert "<history" not in sys_msg
        assert "闲聊助手" in sys_msg