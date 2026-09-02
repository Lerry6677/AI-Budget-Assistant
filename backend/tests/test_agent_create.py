"""POST /agent/expense（create_expense）正式测试。"""
from datetime import datetime


class TestAgentAuth:
    def test_missing_agent_key_returns_401(self, client, user_id):
        resp = client.post(
            "/agent/expense",
            json={"user_id": user_id, "expenses": []},
        )
        assert resp.status_code == 401

    def test_invalid_agent_key_returns_401(self, client, user_id):
        resp = client.post(
            "/agent/expense",
            json={"user_id": user_id, "expenses": []},
            headers={"X-Agent-Key": "wrong-key"},
        )
        assert resp.status_code == 401


class TestCreateExpense:
    def test_create_single(self, client, agent_headers, user_id):
        resp = client.post(
            "/agent/expense",
            json={
                "user_id": user_id,
                "expenses": [
                    {
                        "category": "餐饮",
                        "amount": 25.5,
                        "description": "午饭",
                        "expense_time": "2026-08-20T12:00:00",
                    }
                ],
            },
            headers=agent_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["count"] == 1
        record = body["data"][0]
        assert record["category"] == "餐饮"
        assert record["amount"] == 25.5
        assert record["description"] == "午饭"
        assert record["expense_time"] == "2026-08-20T12:00:00"
        assert record["id"] is not None

    def test_user_id_is_bound_to_record(self, client, agent_headers, user_id):
        resp = client.post(
            "/agent/expense",
            json={
                "user_id": user_id,
                "expenses": [
                    {"category": "交通", "amount": 6.0, "description": "地铁",
                     "expense_time": "2026-08-20T08:00:00"}
                ],
            },
            headers=agent_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"][0]["user_id"] == user_id

    def test_create_batch(self, client, agent_headers, user_id):
        resp = client.post(
            "/agent/expense",
            json={
                "user_id": user_id,
                "expenses": [
                    {"category": "餐饮", "amount": 25.5, "description": "午饭",
                     "expense_time": "2026-08-20T12:00:00"},
                    {"category": "交通", "amount": 6.0, "description": "地铁",
                     "expense_time": "2026-08-20T08:00:00"},
                    {"category": "购物", "amount": 199.0, "description": "键盘",
                     "expense_time": "2026-08-21T20:00:00"},
                ],
            },
            headers=agent_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 3
        # 每条记录字段完整（历史曾出现 ORM 序列化返回 {} 的问题）
        for record in body["data"]:
            assert record["id"] is not None
            assert record["category"]
            assert record["user_id"] == user_id
        amounts = {record["amount"] for record in body["data"]}
        assert amounts == {25.5, 6.0, 199.0}

    def test_natural_language_time_parsing(self, client, agent_headers, user_id):
        resp = client.post(
            "/agent/expense",
            json={
                "user_id": user_id,
                "expenses": [
                    {"category": "餐饮", "amount": 20.0, "description": "午饭",
                     "expense_time_text": "昨天中午"},
                    {"category": "交通", "amount": 4.0, "description": "公交",
                     "expense_time_text": "今天早上"},
                ],
            },
            headers=agent_headers,
        )
        assert resp.status_code == 200
        records = resp.json()["data"]
        times = [datetime.fromisoformat(record["expense_time"]) for record in records]
        # 解析结果只校验时刻部分，日期部分相对运行日不稳定
        assert times[0].hour == 12 and times[0].minute == 0
        assert times[1].hour == 8 and times[1].minute == 0
        # 原文保留入库
        assert records[0]["expense_time_text"] == "昨天中午"

    def test_explicit_time_takes_precedence_over_text(self, client, agent_headers, user_id):
        record = _create_with(client, agent_headers, user_id, expense_time_text="昨天中午",
                              expense_time="2026-01-01T09:30:00")
        assert record["expense_time"] == "2026-01-01T09:30:00"

    def test_unparseable_time_text_leaves_time_null(self, client, agent_headers, user_id):
        record = _create_with(client, agent_headers, user_id, expense_time_text="无法识别的时间")
        assert record["expense_time"] is None
        assert record["expense_time_text"] == "无法识别的时间"

    def test_missing_required_field_returns_422(self, client, agent_headers, user_id):
        resp = client.post(
            "/agent/expense",
            json={
                "user_id": user_id,
                "expenses": [{"category": "餐饮", "description": "缺 amount"}],
            },
            headers=agent_headers,
        )
        assert resp.status_code == 422

    def test_invalid_amount_type_returns_422(self, client, agent_headers, user_id):
        resp = client.post(
            "/agent/expense",
            json={
                "user_id": user_id,
                "expenses": [
                    {"category": "餐饮", "amount": "abc", "description": "金额非法"}
                ],
            },
            headers=agent_headers,
        )
        assert resp.status_code == 422

    def test_missing_user_id_returns_422(self, client, agent_headers):
        resp = client.post(
            "/agent/expense",
            json={"expenses": [{"category": "餐饮", "amount": 10.0, "description": "x"}]},
            headers=agent_headers,
        )
        assert resp.status_code == 422


def _create_with(client, agent_headers, user_id, **overrides):
    expense = {"category": "餐饮", "amount": 10.0, "description": "测试"}
    expense.update(overrides)
    resp = client.post(
        "/agent/expense",
        json={"user_id": user_id, "expenses": [expense]},
        headers=agent_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"][0]
