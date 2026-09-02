"""GET /agent/expense/analyze（analyze_expenses）正式测试。"""
import pytest


@pytest.fixture
def analyze_user(client, agent_headers, user_id):
    """准备固定数据集：8 月餐饮 25.5 + 交通 6.0，9 月购物 199.0。"""
    expenses = [
        {"category": "餐饮", "amount": 25.5, "description": "午饭",
         "expense_time": "2026-08-10T12:00:00"},
        {"category": "交通", "amount": 6.0, "description": "地铁",
         "expense_time": "2026-08-15T08:30:00"},
        {"category": "购物", "amount": 199.0, "description": "键盘",
         "expense_time": "2026-09-05T20:00:00"},
    ]
    resp = client.post(
        "/agent/expense",
        json={"user_id": user_id, "expenses": expenses},
        headers=agent_headers,
    )
    assert resp.status_code == 200
    return user_id


class TestAnalyzeExpenses:
    def test_query_summary_section(self, client, agent_headers, analyze_user):
        resp = client.get(
            "/agent/expense/analyze",
            params={"user_id": analyze_user, "start_date": "2026-08-01", "end_date": "2026-09-30"},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        summary = resp.json()["query_summary"]
        assert summary["expense_count"] == 3
        assert summary["total_amount"] == pytest.approx(230.5)
        categories = {item["category"]: item for item in summary["category_summary"]}
        assert set(categories) == {"餐饮", "交通", "购物"}
        assert categories["购物"]["percentage"] == pytest.approx(199.0 / 230.5 * 100, abs=0.01)

    def test_details_section(self, client, agent_headers, analyze_user):
        resp = client.get(
            "/agent/expense/analyze",
            params={"user_id": analyze_user, "start_date": "2026-08-01", "end_date": "2026-08-31"},
            headers=agent_headers,
        )
        body = resp.json()
        assert len(body["details"]) == 2
        # details 与时间范围一致（9 月购物不在 8 月范围内）
        assert all(detail["expense_time"].startswith("2026-08") for detail in body["details"])
        # query_summary 与 details 数量口径一致
        assert body["query_summary"]["expense_count"] == 2

    def test_profile_section_without_profile(self, client, agent_headers, analyze_user):
        resp = client.get(
            "/agent/expense/analyze",
            params={"user_id": analyze_user},
            headers=agent_headers,
        )
        profile = resp.json()["profile"]
        assert profile == {"savings_goal": None, "financial_goal": None}

    def test_profile_section_with_goals(self, client, agent_headers, analyze_user):
        # 通过已有 agent profile 端点写入目标
        resp = client.post(
            "/agent/profile",
            json={"user_id": analyze_user, "savings_goal": 5000.0, "financial_goal": "买新电脑"},
            headers=agent_headers,
        )
        assert resp.status_code == 200

        resp = client.get(
            "/agent/expense/analyze",
            params={"user_id": analyze_user},
            headers=agent_headers,
        )
        profile = resp.json()["profile"]
        assert profile["savings_goal"] == pytest.approx(5000.0)
        assert profile["financial_goal"] == "买新电脑"

    def test_user_data_isolation(self, client, agent_headers, analyze_user, other_user_id):
        # 另一个用户有自己的账单
        resp = client.post(
            "/agent/expense",
            json={
                "user_id": other_user_id,
                "expenses": [
                    {"category": "娱乐", "amount": 88.0, "description": "电影",
                     "expense_time": "2026-08-12T20:00:00"}
                ],
            },
            headers=agent_headers,
        )
        assert resp.status_code == 200

        resp = client.get(
            "/agent/expense/analyze",
            params={"user_id": other_user_id, "start_date": "2026-08-01", "end_date": "2026-08-31"},
            headers=agent_headers,
        )
        body = resp.json()
        assert body["user_id"] == other_user_id
        # 只能分析到自己的数据
        assert body["query_summary"]["expense_count"] == 1
        assert body["query_summary"]["total_amount"] == pytest.approx(88.0)
        assert all(detail["user_id"] == other_user_id for detail in body["details"])

    def test_analyze_empty_user(self, client, agent_headers, user_id):
        resp = client.get(
            "/agent/expense/analyze",
            params={"user_id": user_id},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["query_summary"]["total_amount"] == 0
        assert body["query_summary"]["expense_count"] == 0
        assert body["details"] == []
