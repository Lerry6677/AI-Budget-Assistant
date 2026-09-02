"""GET /agent/expense/query（query_expenses）正式测试。"""
import pytest


@pytest.fixture
def seeded_user(client, agent_headers, user_id):
    """为测试用户准备固定数据集：8 月两笔餐饮、一笔交通，9 月一笔购物。"""
    expenses = [
        {"category": "餐饮", "amount": 25.5, "description": "午饭",
         "expense_time": "2026-08-10T12:00:00"},
        {"category": "餐饮", "amount": 40.0, "description": "晚饭",
         "expense_time": "2026-08-20T19:00:00"},
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


class TestQueryExpenses:
    def test_date_range_query(self, client, agent_headers, seeded_user):
        resp = client.get(
            "/agent/expense/query",
            params={"user_id": seeded_user, "start_date": "2026-08-01", "end_date": "2026-08-31"},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["expense_count"] == 3
        assert body["total_amount"] == pytest.approx(25.5 + 40.0 + 6.0)

    def test_category_query(self, client, agent_headers, seeded_user):
        resp = client.get(
            "/agent/expense/query",
            params={
                "user_id": seeded_user,
                "start_date": "2026-08-01",
                "end_date": "2026-08-31",
                "category": "餐饮",
            },
            headers=agent_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["expense_count"] == 2
        assert body["total_amount"] == pytest.approx(65.5)
        assert all(item["category"] == "餐饮" for item in body["details"])

    def test_aggregation_summary(self, client, agent_headers, seeded_user):
        resp = client.get(
            "/agent/expense/query",
            params={"user_id": seeded_user, "start_date": "2026-08-01", "end_date": "2026-09-30"},
            headers=agent_headers,
        )
        body = resp.json()
        assert body["expense_count"] == 4
        assert body["total_amount"] == pytest.approx(270.5)
        categories = {item["category"]: item for item in body["category_summary"]}
        assert set(categories) == {"餐饮", "交通", "购物"}
        assert categories["餐饮"]["amount"] == pytest.approx(65.5)
        assert categories["餐饮"]["expense_count"] == 2
        # 占比按总额计算且按金额降序
        assert body["category_summary"][0]["category"] == "购物"
        assert categories["购物"]["percentage"] == pytest.approx(199.0 / 270.5 * 100, abs=0.01)

    def test_details_returned(self, client, agent_headers, seeded_user):
        resp = client.get(
            "/agent/expense/query",
            params={"user_id": seeded_user, "start_date": "2026-08-01", "end_date": "2026-08-31"},
            headers=agent_headers,
        )
        details = resp.json()["details"]
        assert len(details) == 3
        for record in details:
            assert record["id"] is not None
            assert record["user_id"] == seeded_user
            assert record["description"]
        # 明细按时间倒序
        times = [record["expense_time"] for record in details]
        assert times == sorted(times, reverse=True)

    def test_empty_result(self, client, agent_headers, user_id):
        resp = client.get(
            "/agent/expense/query",
            params={"user_id": user_id, "start_date": "2026-01-01", "end_date": "2026-01-31"},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_amount"] == 0
        assert body["expense_count"] == 0
        assert body["category_summary"] == []
        assert body["details"] == []

    def test_user_data_isolation(self, client, agent_headers, seeded_user, other_user_id):
        # 为另一个用户创建一笔账单
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
            "/agent/expense/query",
            params={"user_id": other_user_id, "start_date": "2026-08-01", "end_date": "2026-08-31"},
            headers=agent_headers,
        )
        body = resp.json()
        # 只能看到自己的数据，不受其他用户数据影响
        assert body["expense_count"] == 1
        assert body["total_amount"] == pytest.approx(88.0)
        assert all(record["user_id"] == other_user_id for record in body["details"])

    def test_end_date_before_start_date_returns_400(self, client, agent_headers, user_id):
        resp = client.get(
            "/agent/expense/query",
            params={"user_id": user_id, "start_date": "2026-08-31", "end_date": "2026-08-01"},
            headers=agent_headers,
        )
        assert resp.status_code == 400

    def test_missing_user_id_returns_422(self, client, agent_headers):
        resp = client.get("/agent/expense/query", headers=agent_headers)
        assert resp.status_code == 422
