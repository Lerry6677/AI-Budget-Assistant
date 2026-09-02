"""PUT /agent/expense/{expense_id}（update_expense）正式测试。"""
from datetime import datetime


class TestUpdateExpense:
    def test_update_amount(self, client, agent_headers, user_id, create_expense):
        record = create_expense()
        resp = client.put(
            f"/agent/expense/{record['id']}",
            json={"user_id": user_id, "amount": 99.9},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["amount"] == 99.9

    def test_update_category(self, client, agent_headers, user_id, create_expense):
        record = create_expense()
        resp = client.put(
            f"/agent/expense/{record['id']}",
            json={"user_id": user_id, "category": "聚餐"},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["category"] == "聚餐"

    def test_update_description(self, client, agent_headers, user_id, create_expense):
        record = create_expense()
        resp = client.put(
            f"/agent/expense/{record['id']}",
            json={"user_id": user_id, "description": "和同事聚餐"},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "和同事聚餐"

    def test_update_expense_time(self, client, agent_headers, user_id, create_expense):
        record = create_expense()
        resp = client.put(
            f"/agent/expense/{record['id']}",
            json={"user_id": user_id, "expense_time": "2026-09-01T18:30:00"},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["expense_time"] == "2026-09-01T18:30:00"

    def test_update_expense_time_text_is_parsed(self, client, agent_headers, user_id, create_expense):
        record = create_expense(expense_time="2026-01-01T00:00:00")
        resp = client.put(
            f"/agent/expense/{record['id']}",
            json={"user_id": user_id, "expense_time_text": "昨天中午"},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        parsed = datetime.fromisoformat(resp.json()["expense_time"])
        assert parsed.hour == 12 and parsed.minute == 0

    def test_partial_update_keeps_other_fields(self, client, agent_headers, user_id, create_expense):
        record = create_expense(
            category="餐饮",
            amount=25.5,
            description="午饭",
            expense_time="2026-08-20T12:00:00",
        )
        resp = client.put(
            f"/agent/expense/{record['id']}",
            json={"user_id": user_id, "amount": 30.0},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["amount"] == 30.0
        # 未提交的字段保持不变
        assert body["category"] == "餐饮"
        assert body["description"] == "午饭"
        assert body["expense_time"] == "2026-08-20T12:00:00"

    def test_update_multiple_fields(self, client, agent_headers, user_id, create_expense):
        record = create_expense()
        resp = client.put(
            f"/agent/expense/{record['id']}",
            json={"user_id": user_id, "amount": 50.0, "category": "购物", "description": "新描述"},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["amount"] == 50.0
        assert body["category"] == "购物"
        assert body["description"] == "新描述"

    def test_update_nonexistent_expense_returns_404(self, client, agent_headers, user_id):
        resp = client.put(
            "/agent/expense/99999999",
            json={"user_id": user_id, "amount": 1.0},
            headers=agent_headers,
        )
        assert resp.status_code == 404

    def test_update_other_users_expense_returns_404(
        self, client, agent_headers, create_expense, other_user_id
    ):
        record = create_expense()
        resp = client.put(
            f"/agent/expense/{record['id']}",
            json={"user_id": other_user_id, "amount": 1.0},
            headers=agent_headers,
        )
        assert resp.status_code == 404
        # 原记录未被修改
        query = client.get(
            "/agent/expense/query",
            params={"user_id": record["user_id"]},
            headers=agent_headers,
        )
        assert query.json()["details"][0]["amount"] == 25.5

    def test_update_missing_user_id_returns_422(self, client, agent_headers, create_expense):
        record = create_expense()
        resp = client.put(
            f"/agent/expense/{record['id']}",
            json={"amount": 1.0},
            headers=agent_headers,
        )
        assert resp.status_code == 422
