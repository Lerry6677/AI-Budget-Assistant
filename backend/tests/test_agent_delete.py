"""DELETE /agent/expense/{expense_id}（delete_expense）正式测试。"""


class TestDeleteExpense:
    def test_delete_success(self, client, agent_headers, user_id, create_expense):
        record = create_expense()
        resp = client.delete(
            f"/agent/expense/{record['id']}",
            params={"user_id": user_id},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True}
        # 确认记录已从查询结果中消失
        query = client.get(
            "/agent/expense/query",
            params={"user_id": user_id},
            headers=agent_headers,
        )
        assert query.json()["expense_count"] == 0
        assert query.json()["details"] == []

    def test_delete_repeated_returns_false(self, client, agent_headers, user_id, create_expense):
        record = create_expense()
        first = client.delete(
            f"/agent/expense/{record['id']}",
            params={"user_id": user_id},
            headers=agent_headers,
        )
        assert first.json()["success"] is True
        second = client.delete(
            f"/agent/expense/{record['id']}",
            params={"user_id": user_id},
            headers=agent_headers,
        )
        assert second.status_code == 200
        assert second.json()["success"] is False

    def test_delete_nonexistent_returns_false(self, client, agent_headers, user_id):
        resp = client.delete(
            "/agent/expense/99999999",
            params={"user_id": user_id},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": False}

    def test_delete_other_users_expense_returns_false(
        self, client, agent_headers, create_expense, other_user_id
    ):
        record = create_expense()
        resp = client.delete(
            f"/agent/expense/{record['id']}",
            params={"user_id": other_user_id},
            headers=agent_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        # 原记录仍属于原用户且未被删除
        query = client.get(
            "/agent/expense/query",
            params={"user_id": record["user_id"]},
            headers=agent_headers,
        )
        assert query.json()["expense_count"] == 1

    def test_delete_missing_user_id_returns_422(self, client, agent_headers, create_expense):
        record = create_expense()
        resp = client.delete(
            f"/agent/expense/{record['id']}",
            headers=agent_headers,
        )
        assert resp.status_code == 422
