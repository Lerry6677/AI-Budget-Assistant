"""L3-4 Analyze Tool 完整链路测试。

覆盖：
    1. tools.analyze_expenses 工具层
       - DRY_RUN 模式不连库
       - 真实 SQLite 数据库查询（空结果 / 含 profile / 不含 profile / 时间范围）
    2. router._summarize_analyze 翻译层
       - 空数据 / 满结果 / 含目标 / 不含目标
    3. graph.analyze_node + 路由
       - intent=analyze → analyze_node → END
       - 抽参失败时不抛错
       - 真实 SQLite 端到端
       - 用户隔离（user A 看不到 user B 的数据）
    4. run_agent 端到端
       - run_agent 真实跑 analyze 意图
"""

import pytest

from backend.agent import graph as graph_mod
from backend.agent.prompts import QueryParams
from backend.agent.state import AgentState


# =============================================================================
# 通用 Fixtures
# =============================================================================
@pytest.fixture(autouse=True)
def _dry_run_off(monkeypatch):
    """整个模块默认**真连 SQLite**（conftest 提供的临时库）。"""
    monkeypatch.setattr("backend.agent.tools.DRY_RUN", False)


@pytest.fixture
def fresh_graph():
    """每个测试用独立的 InMemorySaver checkpointer，测试间完全隔离。

    注意：fresh_graph 与 _checkpointer 单例解耦，所以 analyze_node 仍会调
    真实 service 连真 SQLite。
    """
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    compiled = graph_mod._build_graph(checkpointer=saver)
    yield compiled


@pytest.fixture
def mock_intent_analyze(monkeypatch):
    """让 classify_intent 固定返回 analyze。"""
    from backend.agent.prompts import IntentResult

    monkeypatch.setattr(
        "backend.agent.graph.classify_intent",
        lambda _: IntentResult(category="analyze", confidence=0.99, reason="分析"),
    )


@pytest.fixture
def mock_query_params_aug(monkeypatch):
    """Mock classify_query_params：固定返回 8 月范围（便于断言）。"""
    def _fake(_: str) -> QueryParams:
        return QueryParams(
            start_date="2026-08-01",
            end_date="2026-08-31",
            category=None,
        )
    monkeypatch.setattr("backend.agent.graph.classify_query_params", _fake)
    return _fake


@pytest.fixture
def mock_query_params_fail(monkeypatch):
    """Mock 让 classify_query_params 抛错，验证 analyze_node 兜底不中断图。"""
    from backend.agent.prompts import QueryParamExtractError

    monkeypatch.setattr(
        "backend.agent.graph.classify_query_params",
        lambda _: (_ for _ in ()).throw(QueryParamExtractError("mock-analyze-fail")),
    )


def _seed_expenses(client, agent_headers, user_id, expenses):
    """通过 HTTP 端点 seed 数据。"""
    r = client.post(
        "/agent/expense",
        json={"user_id": user_id, "expenses": expenses},
        headers=agent_headers,
    )
    assert r.status_code == 200, r.text
    return r


def _set_profile(client, agent_headers, user_id, savings_goal=None, financial_goal=None):
    """通过 HTTP 端点设置 profile。"""
    payload = {"user_id": user_id}
    if savings_goal is not None:
        payload["savings_goal"] = savings_goal
    if financial_goal is not None:
        payload["financial_goal"] = financial_goal
    r = client.post("/agent/profile", json=payload, headers=agent_headers)
    assert r.status_code == 200, r.text
    return r


# =============================================================================
# 1) tools.analyze_expenses 工具层
# =============================================================================
class TestAnalyzeExpensesTool:
    def test_dry_run_does_not_touch_db(self, monkeypatch, user_id):
        """DRY_RUN 模式下不连库，固定返回 dry_run=True。"""
        monkeypatch.setattr("backend.agent.tools.DRY_RUN", True)
        from backend.agent.tools import analyze_expenses

        result = analyze_expenses.invoke({
            "user_id": user_id,
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
        })
        assert result["dry_run"] is True
        assert result["query_summary"]["expense_count"] == 0
        assert result["details"] == []
        assert result["profile"] == {"savings_goal": None, "financial_goal": None}

    def test_real_db_empty_user(self, user_id):
        """新用户：count=0，profile 字段也返回（值为 None）。"""
        from backend.agent.tools import analyze_expenses

        result = analyze_expenses.invoke({
            "user_id": user_id,
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
        })
        assert result["query_summary"]["expense_count"] == 0
        assert result["query_summary"]["total_amount"] == 0.0
        assert result["details"] == []
        assert "profile" in result
        assert result["profile"]["savings_goal"] is None
        assert result["profile"]["financial_goal"] is None

    def test_real_db_with_data(
        self, client, agent_headers, user_id
    ):
        """seed 3 笔，分析 8 月应有 2 笔（餐饮 25.5 + 交通 6.0），9 月 1 笔购物。"""
        from backend.agent.tools import analyze_expenses

        _seed_expenses(client, agent_headers, user_id, [
            {"category": "餐饮", "amount": 25.5, "description": "午饭",
             "expense_time": "2026-08-10T12:00:00"},
            {"category": "交通", "amount": 6.0, "description": "地铁",
             "expense_time": "2026-08-15T08:30:00"},
            {"category": "购物", "amount": 199.0, "description": "键盘",
             "expense_time": "2026-09-05T20:00:00"},
        ])

        r1 = analyze_expenses.invoke({
            "user_id": user_id,
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
        })
        assert r1["query_summary"]["expense_count"] == 2
        assert abs(r1["query_summary"]["total_amount"] - 31.5) < 0.01
        cats = {b["category"]: b for b in r1["query_summary"]["category_summary"]}
        assert set(cats) == {"餐饮", "交通"}

        r2 = analyze_expenses.invoke({
            "user_id": user_id,
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
        })
        assert r2["query_summary"]["expense_count"] == 1
        assert r2["query_summary"]["total_amount"] == 199.0
        cats2 = {b["category"]: b for b in r2["query_summary"]["category_summary"]}
        assert cats2["购物"]["percentage"] == pytest.approx(100.0)

    def test_real_db_with_profile(
        self, client, agent_headers, user_id
    ):
        """seed 账单 + 设置 profile，分析结果应包含 savings_goal / financial_goal。"""
        from backend.agent.tools import analyze_expenses

        _seed_expenses(client, agent_headers, user_id, [
            {"category": "餐饮", "amount": 100.0, "description": "午餐",
             "expense_time": "2026-08-10T12:00:00"},
        ])
        _set_profile(client, agent_headers, user_id,
                     savings_goal=5000.0, financial_goal="买新电脑")

        r = analyze_expenses.invoke({
            "user_id": user_id,
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
        })
        assert r["profile"]["savings_goal"] == pytest.approx(5000.0)
        assert r["profile"]["financial_goal"] == "买新电脑"

    def test_invalid_date_range_returns_empty(self, user_id):
        """start > end 时返回空结果（不抛错）。"""
        from backend.agent.tools import analyze_expenses

        r = analyze_expenses.invoke({
            "user_id": user_id,
            "start_date": "2026-12-31",
            "end_date": "2026-01-01",
        })
        assert r["query_summary"]["expense_count"] == 0


# =============================================================================
# 2) router._summarize_analyze 翻译层
# =============================================================================
class TestSummarizeAnalyze:
    def test_empty_data_message(self):
        from backend.agent.router import _summarize_analyze
        msg = _summarize_analyze({
            "query_summary": {"total_amount": 0.0, "expense_count": 0, "category_summary": []},
            "details": [],
            "profile": {"savings_goal": None, "financial_goal": None},
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
        })
        assert "无可分析数据" in msg

    def test_full_data_message_includes_categories_and_total(self):
        from backend.agent.router import _summarize_analyze
        msg = _summarize_analyze({
            "query_summary": {
                "total_amount": 230.5,
                "expense_count": 3,
                "category_summary": [
                    {"category": "购物", "amount": 199.0, "percentage": 86.33, "expense_count": 1},
                    {"category": "餐饮", "amount": 25.5, "percentage": 11.06, "expense_count": 1},
                    {"category": "交通", "amount": 6.0, "percentage": 2.60, "expense_count": 1},
                ],
            },
            "details": [],
            "profile": {"savings_goal": None, "financial_goal": None},
            "start_date": "2026-08-01",
            "end_date": "2026-09-30",
        })
        assert "230.5" in msg
        assert "3 笔" in msg
        assert "分类占比" in msg
        # 三个分类都要列出来
        for cat in ("购物", "餐饮", "交通"):
            assert cat in msg
        # 比例保留 1 位小数
        assert "86.3%" in msg

    def test_with_profile_goals(self):
        from backend.agent.router import _summarize_analyze
        msg = _summarize_analyze({
            "query_summary": {
                "total_amount": 100.0,
                "expense_count": 1,
                "category_summary": [{"category": "餐饮", "amount": 100.0,
                                      "percentage": 100.0, "expense_count": 1}],
            },
            "details": [],
            "profile": {"savings_goal": 5000.0, "financial_goal": "买新电脑"},
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
        })
        assert "储蓄目标 5000" in msg
        assert "买新电脑" in msg
        assert "对比目标" in msg

    def test_without_profile_goals(self):
        from backend.agent.router import _summarize_analyze
        msg = _summarize_analyze({
            "query_summary": {
                "total_amount": 50.0,
                "expense_count": 1,
                "category_summary": [],
            },
            "details": [],
            "profile": {"savings_goal": None, "financial_goal": None},
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
        })
        assert "未设置" in msg

    def test_dry_run_message(self):
        from backend.agent.router import _summarize_analyze
        msg = _summarize_analyze({
            "query_summary": {"total_amount": 0.0, "expense_count": 0, "category_summary": []},
            "details": [],
            "profile": {"savings_goal": None, "financial_goal": None},
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "dry_run": True,
        })
        assert "DRY_RUN" in msg


# =============================================================================
# 3) graph.analyze_node 节点 + 路由
# =============================================================================
class TestAnalyzeNode:
    def test_analyze_node_routes_correctly(
        self, fresh_graph, mock_intent_analyze, mock_query_params_aug,
        client, agent_headers, user_id,
    ):
        """intent=analyze → analyze_node → END。无数据时返回"无可分析数据"。"""
        state = fresh_graph.invoke(
            {"user_id": user_id, "input": "分析一下我这月消费"},
            config={"configurable": {"thread_id": f"l34_{user_id}_1"}},
        )
        assert state["intent"] == "analyze"
        assert "无可分析数据" in state["reply"]

    def test_analyze_node_end_to_end_with_data(
        self, mock_intent_analyze, mock_query_params_aug,
        client, agent_headers, user_id,
    ):
        """完整链路：seed 数据 → 直接调 analyze_node → 返回含分类占比的回复。"""
        from backend.agent.graph import analyze_node

        _seed_expenses(client, agent_headers, user_id, [
            {"category": "餐饮", "amount": 50.0, "description": "午餐",
             "expense_time": "2026-08-10T12:00:00"},
            {"category": "交通", "amount": 10.0, "description": "地铁",
             "expense_time": "2026-08-15T08:00:00"},
        ])

        s = analyze_node({
            "user_id": user_id,
            "input": "分析 8 月",
            "intent": "analyze",
            "intent_confidence": 1.0,
            "messages": [],
        })
        assert "60" in s["reply"] or "50" in s["reply"]  # 总额或某分类
        assert "餐饮" in s["reply"]
        assert "交通" in s["reply"]
        assert "分类占比" in s["reply"]

    def test_analyze_node_handles_extract_failure(
        self, fresh_graph, mock_intent_analyze, mock_query_params_fail, user_id,
    ):
        """抽参失败时 analyze_node 返回友好错误，不抛错打断图。"""
        state = fresh_graph.invoke(
            {"user_id": user_id, "input": "随便分析"},
            config={"configurable": {"thread_id": f"l34_fail_{user_id}"}},
        )
        assert "分析参数解析失败" in state["reply"] or "mock-analyze-fail" in state["reply"]

    def test_analyze_node_user_isolation(
        self, mock_intent_analyze, mock_query_params_aug,
        client, agent_headers, user_id, other_user_id,
    ):
        """User A 看不到 User B 的数据（隔离靠 user_id）。"""
        from backend.agent.graph import analyze_node

        # B 有数据
        _seed_expenses(client, agent_headers, other_user_id, [
            {"category": "娱乐", "amount": 9999.0, "description": "B的奢华娱乐",
             "expense_time": "2026-08-12T20:00:00"},
        ])
        # A 调 analyze_node
        s = analyze_node({
            "user_id": user_id,
            "input": "分析 8 月",
            "intent": "analyze",
            "intent_confidence": 1.0,
            "messages": [],
        })
        assert "9999" not in s["reply"], "User A 看到了 User B 的数据（隔离失败）"
        assert "无可分析数据" in s["reply"]


# =============================================================================
# 4) run_agent 端到端
# =============================================================================
class TestRunAgentAnalyze:
    def test_run_agent_analyze_intent(
        self, monkeypatch, mock_intent_analyze, mock_query_params_aug,
        client, agent_headers, user_id,
    ):
        """run_agent 真实跑：analyze 意图 → analyze_node → 返回含分类占比的回复。"""
        # 重置 graph 单例 + checkpointer
        graph_mod.reset_graph_for_tests()
        from langgraph.checkpoint.memory import InMemorySaver

        monkeypatch.setattr("backend.agent.graph._checkpointer", InMemorySaver())

        # seed + profile
        _seed_expenses(client, agent_headers, user_id, [
            {"category": "餐饮", "amount": 80.0, "description": "本月大餐",
             "expense_time": "2026-08-15T12:00:00"},
            {"category": "购物", "amount": 120.0, "description": "衣服",
             "expense_time": "2026-08-20T19:00:00"},
        ])
        _set_profile(client, agent_headers, user_id,
                     savings_goal=1000.0, financial_goal="买基金")

        reply = graph_mod.run_agent(
            user_id=user_id,
            user_input="分析我本月消费",
            thread_id=f"l34_run_{user_id}",
        )
        # 含分类占比
        assert "分类占比" in reply
        assert "餐饮" in reply
        assert "购物" in reply
        # 含目标对比
        assert "1000" in reply
        assert "买基金" in reply
        # 含总额
        assert "200" in reply  # 80 + 120
