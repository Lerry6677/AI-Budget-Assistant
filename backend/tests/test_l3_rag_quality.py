"""Task 20：RAG 召回质量 + 可观测性测试。

覆盖：
    1. 模块常量 RAG_DEFAULT_MIN_SIMILARITY / RAG_DEFAULT_TOP_K 暴露
    2. retrieve_similar / retrieve_similar_cross_thread return_meta=True 返回 meta
    3. meta 字段齐全：hits / avg_sim / max_sim / took_ms / mode
    4. similarity ∈ [0, 1]（TF-IDF cosine 性质）
    5. 跨 thread 默认去重：相邻相同 user_input 只留1 条
    6. dedup=False 时不去重
    7. top_k 上调/下调生效
    8. min_similarity 阈值严格/宽松生效
    9. created_at 透传（meta 不需要，但返回 hit dict 带）
    10. 隔离回归：user / thread 隔离不被破坏
    11. chat_node 触发 logger.info 输出 RAG meta
    12. chat_node 无历史时 meta.hits=0 仍被记录

不覆盖：
    - similarity 默认值是否调整（Task 20 明确不改，保持 0.05）
    - LLM 注入 prompt 是否含 similarity（明确不注入，prompt 文本检查跳过）
"""

from __future__ import annotations

import logging

import pytest

from backend.agent import graph as graph_mod
from backend.agent import rag
from backend.agent.prompts import IntentResult


# =============================================================================
# 1. 常量契约
# =============================================================================
class TestRagConstants:
    def test_default_min_similarity_constant_exists(self):
        """RAG_DEFAULT_MIN_SIMILARITY 必须暴露，保持 L3-6 的 0.05。"""
        assert hasattr(rag, "RAG_DEFAULT_MIN_SIMILARITY")
        assert rag.RAG_DEFAULT_MIN_SIMILARITY == 0.05

    def test_default_top_k_constant_exists(self):
        assert hasattr(rag, "RAG_DEFAULT_TOP_K")
        assert rag.RAG_DEFAULT_TOP_K == 5


# =============================================================================
# 2. meta 返回结构
# =============================================================================
class TestRetrieveReturnsMeta:
    def test_retrieve_similar_return_meta(self, user_id):
        rag.save_chat(user_id, "t", "咖啡我喜欢", "好的")
        hits, meta = rag.retrieve_similar(
            user_id=user_id, thread_id="t", query="我喜欢咖啡",
            return_meta=True,
        )
        assert isinstance(hits, list)
        assert isinstance(meta, dict)
        assert meta["mode"] == "single_thread"
        for k in ("hits", "avg_sim", "max_sim", "took_ms", "top_k", "min_similarity"):
            assert k in meta, f"meta 缺字段 {k}"

    def test_retrieve_similar_no_meta_by_default(self, user_id):
        """return_meta=False（默认）→ 只返回 list，不返回 tuple。"""
        rag.save_chat(user_id, "t", "咖啡我喜欢", "好的")
        result = rag.retrieve_similar(
            user_id=user_id, thread_id="t", query="我喜欢咖啡",
        )
        assert isinstance(result, list)

    def test_retrieve_cross_thread_return_meta(self, user_id):
        rag.save_chat(user_id, "t1", "我月薪多少", "5 万")
        hits, meta = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="我的月薪",
            exclude_thread_id="t2", return_meta=True,
        )
        assert isinstance(hits, list)
        assert isinstance(meta, dict)
        assert meta["mode"] == "cross_thread"
        for k in ("hits", "avg_sim", "max_sim", "took_ms", "top_k",
                  "min_similarity", "deduped", "filtered_out_by_threshold"):
            assert k in meta, f"meta 缺字段 {k}"

    def test_meta_zero_hits_when_no_history(self, user_id):
        """无历史时 meta 仍存在、hits=0、不抛错。"""
        _, meta = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="随便问", return_meta=True,
        )
        assert meta["hits"] == 0
        assert meta["avg_sim"] == 0.0
        assert meta["max_sim"] == 0.0
        assert meta["took_ms"] >= 0.0

    def test_build_section_returns_meta(self, user_id):
        rag.save_chat(user_id, "t1", "测试名", "Alpha")
        section, meta = rag.build_rag_prompt_section_cross_thread(
            user_id=user_id, query="测试名",
            return_meta=True,
        )
        assert isinstance(section, str)
        assert isinstance(meta, dict)
        assert meta["mode"] == "cross_thread"

    def test_build_section_empty_history(self, user_id):
        section, meta = rag.build_rag_prompt_section_cross_thread(
            user_id=user_id, query="随便", return_meta=True,
        )
        assert section == ""
        assert meta["hits"] == 0


# =============================================================================
# 3. similarity 数值性质
# =============================================================================
class TestSimilarityRange:
    def test_similarity_in_unit_interval(self, user_id):
        rag.save_chat(user_id, "t", "我今天搭乘出租车", "好的")
        hits = rag.retrieve_similar(
            user_id=user_id, thread_id="t", query="我今天打车", top_k=1,
        )
        assert len(hits) >= 1
        sim = hits[0]["similarity"]
        assert 0.0 <= sim <= 1.0, f"similarity 应在 [0,1]，实际 {sim}"

    def test_similarity_monotonic_descending(self, user_id):
        """top_k>1 时，结果按相似度降序。"""
        for i in range(5):
            rag.save_chat(user_id, "t", f"我爱喝咖啡{i}", "ok")
        hits = rag.retrieve_similar(
            user_id=user_id, thread_id="t", query="我爱喝咖啡", top_k=5,
            min_similarity=0.0,
        )
        sims = [h["similarity"] for h in hits]
        assert sims == sorted(sims, reverse=True), (
            f"hits 应按 similarity 降序，实际 {sims}"
        )


# =============================================================================
# 4. 跨 thread 去重
# =============================================================================
class TestCrossThreadDedup:
    def test_default_dedup_removes_near_duplicates(self, user_id):
        """默认 dedup=True：相邻相同 user_input 只留 1 条。"""
        rag.save_chat(user_id, "t1", "我喜欢喝咖啡", "好1")
        rag.save_chat(user_id, "t2", "我喜欢喝咖啡", "好2")  # 几乎重复
        rag.save_chat(user_id, "t3", "我喜欢喝咖啡  ", "好3")  # 尾随空格

        hits = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="我喜欢喝咖啡",
            top_k=5, min_similarity=0.0,
        )
        # 3 条全归一化相同 → 应只剩 1 条
        assert len(hits) == 1, f"dedup 默认应去重，实际 {len(hits)} 条"

    def test_dedup_false_keeps_all(self, user_id):
        """dedup=False 时不去重。"""
        rag.save_chat(user_id, "t1", "我喜欢喝咖啡", "好1")
        rag.save_chat(user_id, "t2", "我喜欢喝咖啡", "好2")

        hits = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="我喜欢喝咖啡",
            top_k=5, min_similarity=0.0, dedup=False,
        )
        assert len(hits) == 2, f"dedup=False 应保留全部，实际 {len(hits)}"

    def test_dedup_keeps_highest_similarity(self, user_id):
        """去重时按相似度降序保留更高者。"""
        # t1 写相关问题（更接近 query），t2 写几乎相同问题
        rag.save_chat(user_id, "t1", "我喜欢喝咖啡", "好1")
        rag.save_chat(user_id, "t2", "我喜欢喝咖啡", "好2")
        rag.save_chat(user_id, "t3", "完全无关的内容 xyz", "好3")

        hits = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="我喜欢喝咖啡",
            top_k=3, min_similarity=0.0,
        )
        # 3 条原始，dedup 后应只剩 2 条（咖啡和无关）
        assert len(hits) == 2
        user_inputs = [h["user_input"] for h in hits]
        assert "我喜欢喝咖啡" in user_inputs
        assert "完全无关的内容 xyz" in user_inputs

    def test_dedup_meta_records_deduped_count(self, user_id):
        rag.save_chat(user_id, "t1", "我喜欢喝咖啡", "好1")
        rag.save_chat(user_id, "t2", "我喜欢喝咖啡", "好2")
        _, meta = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="我喜欢喝咖啡",
            top_k=5, min_similarity=0.0, return_meta=True,
        )
        # 至少有 1 条因 dedup 被丢弃
        assert meta["deduped"] >= 1


# =============================================================================
# 5. top_k / min_similarity 参数生效
# =============================================================================
class TestTopKAndThreshold:
    def test_top_k_override_limits_results(self, user_id):
        for i in range(8):
            rag.save_chat(user_id, f"t{i}", f"我爱喝咖啡{i}", "ok")
        hits = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="我爱喝咖啡",
            top_k=2, min_similarity=0.0, dedup=False,
        )
        assert len(hits) == 2

    def test_top_k_higher_returns_more(self, user_id):
        for i in range(8):
            rag.save_chat(user_id, f"t{i}", f"我爱喝咖啡{i}", "ok")
        h2 = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="我爱喝咖啡",
            top_k=2, min_similarity=0.0, dedup=False,
        )
        h5 = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="我爱喝咖啡",
            top_k=5, min_similarity=0.0, dedup=False,
        )
        assert len(h2) == 2
        assert len(h5) == 5

    def test_strict_threshold_filters_out_noise(self, user_id):
        rag.save_chat(user_id, "t1", "我喜欢喝咖啡", "好的")
        loose = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="我今天搭乘出租车去机场",
            top_k=5, min_similarity=0.0, dedup=False,
        )
        strict = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="我今天搭乘出租车去机场",
            top_k=5, min_similarity=0.5, dedup=False,
        )
        # 严格阈值应比宽松返回更少（或等量，但不会更多）
        assert len(strict) <= len(loose)
        # 严格版完全过滤噪音
        assert strict == []


# =============================================================================
# 6. created_at 透传
# =============================================================================
class TestCreatedAtMeta:
    def test_single_thread_hits_have_created_at(self, user_id):
        rag.save_chat(user_id, "t", "咖啡", "ok")
        hits = rag.retrieve_similar(
            user_id=user_id, thread_id="t", query="咖啡", top_k=1,
        )
        assert len(hits) >= 1
        assert "created_at" in hits[0]
        # 允许 None（如果 created_at 字段为空），但 key 必须存在
        assert hits[0]["created_at"] is None or isinstance(hits[0]["created_at"], str)

    def test_cross_thread_hits_have_created_at(self, user_id):
        rag.save_chat(user_id, "t1", "测试名", "Alpha")
        hits = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="测试名", top_k=1,
        )
        assert len(hits) >= 1
        assert "created_at" in hits[0]


# =============================================================================
# 7. 隔离回归（不破 L3-5/L3-6）
# =============================================================================
class TestIsolationRegression:
    def test_user_isolation_unchanged(self, user_id, other_user_id):
        """Task 20 不应破坏 user 隔离。"""
        rag.save_chat(user_id, "iso_t", "我月薪 5 万", "好的")
        hits = rag.retrieve_similar_cross_thread(
            user_id=other_user_id, query="月薪", top_k=5,
        )
        assert all(h["user_input"] != "我月薪 5 万" for h in hits)

    def test_thread_exclusion_unchanged(self, user_id):
        """exclude_thread_id 仍生效。"""
        rag.save_chat(user_id, "current_t", "咖啡我喜欢", "好的")
        rag.save_chat(user_id, "other_t", "今天天气真好", "是的")
        hits = rag.retrieve_similar_cross_thread(
            user_id=user_id, query="咖啡",
            exclude_thread_id="current_t",
        )
        assert all(h["thread_id"] != "current_t" for h in hits)

    def test_return_meta_does_not_leak_user(self, user_id, other_user_id):
        """return_meta=True 不破坏 user 隔离。"""
        rag.save_chat(user_id, "t", "我的薪酬", "5 万")
        hits, meta = rag.retrieve_similar_cross_thread(
            user_id=other_user_id, query="薪酬",
            return_meta=True,
        )
        assert hits == []
        assert meta["hits"] == 0
        assert meta["user_id"] == other_user_id


# =============================================================================
# 8. chat_node logger 输出 RAG meta
# =============================================================================
class TestChatNodeLogging:
    """验证 chat_node 触发 `chat_node.rag_meta` 日志输出。"""

    @pytest.fixture
    def mock_chat_chain(self, monkeypatch):
        class _R:
            content = "pong"
        monkeypatch.setattr(
            "backend.agent.graph._get_chat_chain",
            lambda: type("C", (), {"invoke": staticmethod(lambda _: _R())})(),
        )

    @pytest.fixture
    def mock_intent_chat(self, monkeypatch):
        monkeypatch.setattr(
            "backend.agent.graph.classify_intent",
            lambda _: IntentResult(category="chat", confidence=0.99, reason="chat"),
        )

    def test_chat_node_logs_rag_meta_with_history(
        self, monkeypatch, user_id, mock_chat_chain, mock_intent_chat
    ):
        """有历史时 chat_node 输出 hits/avg_sim/max_sim。"""
        from langgraph.checkpoint.memory import InMemorySaver

        rag.save_chat(user_id, "seed_t", "我的测试名", "Alpha")

        records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Capture(level=logging.INFO)
        logger = logging.getLogger("backend.agent.graph")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            compiled = graph_mod._build_graph(checkpointer=InMemorySaver())
            compiled.invoke(
                {
                    "user_id": user_id,
                    "input": "我的测试名？",
                    "thread_id": "current_t",
                },
                config={"configurable": {"thread_id": "current_t"}},
            )
        finally:
            logger.removeHandler(handler)

        # 至少 1 条 chat_node.rag_meta 日志
        rag_logs = [r for r in records if "chat_node.rag_meta" in r.getMessage()]
        assert len(rag_logs) >= 1, (
            f"chat_node 必须输出 rag_meta 日志，实际 records={[r.getMessage() for r in records]}"
        )
        msg = rag_logs[0].getMessage()
        assert "hits=" in msg
        assert "took_ms=" in msg
        assert "user_id=" in msg

    def test_chat_node_logs_zero_hits_when_no_history(
        self, monkeypatch, user_id, mock_chat_chain, mock_intent_chat
    ):
        """无历史时 chat_node 仍输出 hits=0。"""
        from langgraph.checkpoint.memory import InMemorySaver

        records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Capture(level=logging.INFO)
        logger = logging.getLogger("backend.agent.graph")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            compiled = graph_mod._build_graph(checkpointer=InMemorySaver())
            compiled.invoke(
                {"user_id": user_id, "input": "你好", "thread_id": "fresh_t"},
                config={"configurable": {"thread_id": "fresh_t"}},
            )
        finally:
            logger.removeHandler(handler)

        rag_logs = [r for r in records if "chat_node.rag_meta" in r.getMessage()]
        assert len(rag_logs) >= 1
        msg = rag_logs[0].getMessage()
        assert "hits=0" in msg