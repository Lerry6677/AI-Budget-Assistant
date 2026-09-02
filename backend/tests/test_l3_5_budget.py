"""L3-5 Budget Tool 完整链路测试。

覆盖：
    1. tools.update_user_profile 工具层（DRY_RUN / 真库 / 含 financial_goal）
    2. tools.get_user_profile 工具层
    3. router._summarize_budget 翻译层
    4. graph.budget_node 节点 + 路由
    5. run_agent 端到端（budget 意图）
"""

import pytest

from backend.agent import graph as graph_mod
from backend.agent.prompts import BudgetParams


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture(autouse=True)
def _dry_run_off(monkeypatch):
    monkeypatch.setattr("backend.agent.tools.DRY_RUN", False)


@pytest.fixture
def mock_intent_budget(monkeypatch):
    """让 classify_intent 固定返回 budget。"""
    from backend.agent.prompts import IntentResult

    monkeypatch.setattr(
        "backend.agent.graph.classify_intent",
        lambda _: IntentResult(category="budget", confidence=0.99, reason="预算"),
    )


@pytest.fixture
def mock_budget_params_savings(monkeypatch):
    """Mock classify_budget_params：固定返回 {savings_goal=5000}。"""
    def _fake(_: str) -> BudgetParams:
        return BudgetParams(savings_goal=5000.0, financial_goal=None)
    monkeypatch.setattr("backend.agent.graph.classify_budget_params", _fake)
    return _fake


@pytest.fixture
def mock_budget_params_full(monkeypatch):
    """Mock classify_budget_params：返回 {savings_goal=1000, financial_goal='买电脑'}。"""
    def _fake(_: str) -> BudgetParams:
        return BudgetParams(savings_goal=1000.0, financial_goal="买新电脑")
    monkeypatch.setattr("backend.agent.graph.classify_budget_params", _fake)
    return _fake


@pytest.fixture
def mock_budget_params_empty(monkeypatch):
    """Mock classify_budget_params：用户没提具体目标（两个都 None）。"""
    def _fake(_: str) -> BudgetParams:
        return BudgetParams(savings_goal=None, financial_goal=None)
    monkeypatch.setattr("backend.agent.graph.classify_budget_params", _fake)
    return _fake


@pytest.fixture
def mock_budget_params_fail(monkeypatch):
    from backend.agent.prompts import BudgetParamExtractError

    monkeypatch.setattr(
        "backend.agent.graph.classify_budget_params",
        lambda _: (_ for _ in ()).throw(BudgetParamExtractError("mock-budget-fail")),
    )


# =============================================================================
# 1) tools.update_user_profile
# =============================================================================
class TestUpdateUserProfileTool:
    def test_dry_run_does_not_touch_db(self, monkeypatch, user_id):
        monkeypatch.setattr("backend.agent.tools.DRY_RUN", True)
        from backend.agent.tools import update_user_profile

        r = update_user_profile.invoke({
            "user_id": user_id,
            "savings_goal": 5000.0,
            "financial_goal": "买电脑",
        })
        assert r["dry_run"] is True
        assert r["savings_goal"] == 5000.0
        assert r["financial_goal"] == "买电脑"

    def test_real_db_savings_only(self, user_id):
        from backend.agent.tools import update_user_profile, get_user_profile

        r = update_user_profile.invoke({
            "user_id": user_id,
            "savings_goal": 5000.0,
            "financial_goal": None,
        })
        assert r["savings_goal"] == pytest.approx(5000.0)
        assert r.get("financial_goal") in (None, "")

        # 再读回：持久化生效
        p = get_user_profile.invoke({"user_id": user_id})
        assert p["savings_goal"] == pytest.approx(5000.0)

    def test_real_db_full_profile(self, user_id):
        from backend.agent.tools import update_user_profile

        r = update_user_profile.invoke({
            "user_id": user_id,
            "savings_goal": 8000.0,
            "financial_goal": "买新电脑",
        })
        assert r["savings_goal"] == pytest.approx(8000.0)
        assert r["financial_goal"] == "买新电脑"

    def test_real_db_isolated_by_user(self, user_id, other_user_id):
        from backend.agent.tools import get_user_profile, update_user_profile

        update_user_profile.invoke({
            "user_id": user_id,
            "savings_goal": 5000.0,
            "financial_goal": None,
        })
        # B 看不到 A
        p = get_user_profile.invoke({"user_id": other_user_id})
        assert p["savings_goal"] is None
        assert p["financial_goal"] is None


# =============================================================================
# 2) tools.get_user_profile
# =============================================================================
class TestGetUserProfileTool:
    def test_dry_run(self, monkeypatch, user_id):
        monkeypatch.setattr("backend.agent.tools.DRY_RUN", True)
        from backend.agent.tools import get_user_profile

        r = get_user_profile.invoke({"user_id": user_id})
        assert r["dry_run"] is True
        assert r["savings_goal"] is None
        assert r["financial_goal"] is None

    def test_empty_user_returns_none(self, user_id):
        from backend.agent.tools import get_user_profile

        r = get_user_profile.invoke({"user_id": user_id})
        assert r["savings_goal"] is None
        assert r["financial_goal"] is None


# =============================================================================
# 3) router._summarize_budget
# =============================================================================
class TestSummarizeBudget:
    def test_savings_only(self):
        from backend.agent.router import _summarize_budget
        msg = _summarize_budget({
            "savings_goal": 5000.0,
            "financial_goal": None,
        })
        assert "5000" in msg
        assert "储蓄目标" in msg

    def test_financial_goal_only(self):
        from backend.agent.router import _summarize_budget
        msg = _summarize_budget({
            "savings_goal": None,
            "financial_goal": "买新电脑",
        })
        assert "买新电脑" in msg
        assert "财务目标" in msg

    def test_both(self):
        from backend.agent.router import _summarize_budget
        msg = _summarize_budget({
            "savings_goal": 1000.0,
            "financial_goal": "买基金",
        })
        assert "1000" in msg
        assert "买基金" in msg
        assert "✅" in msg or "已更新" in msg

    def test_no_goals_friendly_prompt(self):
        from backend.agent.router import _summarize_budget
        msg = _summarize_budget({
            "savings_goal": None,
            "financial_goal": None,
        })
        assert "未识别" in msg or "请说明" in msg

    def test_error_message(self):
        from backend.agent.router import _summarize_budget
        msg = _summarize_budget({"error": "连接超时"})
        assert "失败" in msg
        assert "连接超时" in msg

    def test_dry_run_message(self):
        from backend.agent.router import _summarize_budget
        msg = _summarize_budget({
            "savings_goal": 100.0,
            "financial_goal": None,
            "dry_run": True,
        })
        assert "DRY_RUN" in msg


# =============================================================================
# 4) graph.budget_node + 路由
# =============================================================================
class TestBudgetNode:
    def test_budget_node_routes_and_saves_profile(
        self, mock_intent_budget, mock_budget_params_savings,
    ):
        """intent=budget → budget_node → 真实更新 profile。"""
        from backend.agent.graph import budget_node
        from backend.agent.tools import get_user_profile

        user_id = "pytest_budget_node_user"
        try:
            s = budget_node({
                "user_id": user_id,
                "input": "我每月想存 5000",
                "intent": "budget",
                "intent_confidence": 1.0,
                "messages": [],
            })
            assert "5000" in s["reply"]
            # 真的写库了
            p = get_user_profile.invoke({"user_id": user_id})
            assert p["savings_goal"] == pytest.approx(5000.0)
        finally:
            # 清理（不走 conftest，因为不是 conftest fixture）
            from backend.database import SessionLocal
            from backend.models.user_profile import UserProfile
            db = SessionLocal()
            try:
                db.query(UserProfile).filter(UserProfile.user_id == user_id).delete()
                db.commit()
            finally:
                db.close()

    def test_budget_node_full(
        self, mock_intent_budget, mock_budget_params_full, user_id
    ):
        from backend.agent.graph import budget_node
        from backend.agent.tools import get_user_profile

        s = budget_node({
            "user_id": user_id,
            "input": "我要存 1000 买电脑",
            "intent": "budget",
            "intent_confidence": 1.0,
            "messages": [],
        })
        assert "1000" in s["reply"]
        assert "买新电脑" in s["reply"]
        p = get_user_profile.invoke({"user_id": user_id})
        assert p["savings_goal"] == pytest.approx(1000.0)
        assert p["financial_goal"] == "买新电脑"

    def test_budget_node_handles_empty_params(
        self, mock_intent_budget, mock_budget_params_empty, user_id
    ):
        from backend.agent.graph import budget_node
        s = budget_node({
            "user_id": user_id,
            "input": "我想存钱",
            "intent": "budget",
            "intent_confidence": 1.0,
            "messages": [],
        })
        assert "未识别" in s["reply"] or "请说明" in s["reply"]

    def test_budget_node_handles_extract_failure(
        self, mock_intent_budget, mock_budget_params_fail, user_id
    ):
        from backend.agent.graph import budget_node
        s = budget_node({
            "user_id": user_id,
            "input": "随便",
            "intent": "budget",
            "intent_confidence": 1.0,
            "messages": [],
        })
        assert "预算参数解析失败" in s["reply"]

    def test_budget_node_does_not_write_chat_history(
        self, mock_intent_budget, mock_budget_params_full, user_id,
    ):
        """budget 节点不属于"闲聊"，不应写 chat_history。"""
        from backend.agent.graph import budget_node
        from backend.database import SessionLocal
        from backend.models import ChatHistory

        before = SessionLocal().query(ChatHistory).filter(
            ChatHistory.user_id == user_id
        ).count()
        budget_node({
            "user_id": user_id,
            "input": "我要存 1000 买电脑",
            "intent": "budget",
            "intent_confidence": 1.0,
            "messages": [],
        })
        after = SessionLocal().query(ChatHistory).filter(
            ChatHistory.user_id == user_id
        ).count()
        assert before == after, "budget 节点不应写 chat_history"


# =============================================================================
# 5) run_agent 端到端
# =============================================================================
class TestRunAgentBudget:
    def test_run_agent_budget_intent(
        self, monkeypatch, mock_intent_budget, mock_budget_params_savings,
    ):
        """run_agent 真实跑：budget 意图 → budget_node → 更新 profile。"""
        graph_mod.reset_graph_for_tests()
        from langgraph.checkpoint.memory import InMemorySaver

        monkeypatch.setattr("backend.agent.graph._checkpointer", InMemorySaver())
        from backend.agent.tools import get_user_profile

        user_id = "pytest_run_budget"
        try:
            reply = graph_mod.run_agent(
                user_id=user_id,
                user_input="我每月想存 5000",
                thread_id=f"l35_budget_{user_id}",
            )
            assert "5000" in reply
            p = get_user_profile.invoke({"user_id": user_id})
            assert p["savings_goal"] == pytest.approx(5000.0)
        finally:
            from backend.database import SessionLocal
            from backend.models.user_profile import UserProfile
            db = SessionLocal()
            try:
                db.query(UserProfile).filter(UserProfile.user_id == user_id).delete()
                db.commit()
            finally:
                db.close()
