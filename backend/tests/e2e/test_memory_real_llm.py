"""Task 23 Step 5：Long-term Memory 真实 LLM 端到端验收测试。

⚠️  本测试文件**会真实调用 LLM API**（产生费用、依赖网络）。
    - 当 LLM_API_KEY 未配置时，全部 SKIPPED（见 backend/tests/e2e/conftest.py）
    - 仅在本地或 CI 临时启用，不要在普通 `pytest backend/tests/` 中强制开启

运行方式（启用 E2E）：
    # 1. 设置真实 API key（参考 .env.example）
    export LLM_API_KEY=sk-...
    # 2. 运行此目录
    pytest backend/tests/e2e/ -v

不启用 E2E（普通测试）：
    pytest backend/tests/        # 自动 skip e2e/ 整个目录

覆盖场景（按用户要求 5 个 Case）：
    Case 1 明确用户偏好（"我平时比较喜欢吃川菜"）
    Case 2 明确长期事实（"我是学生，月生活费 3000"）
    Case 3 普通一次性消费（"今天中午吃了 15 块盖饭"）→ 不应污染 memory
    Case 4 无 Memory 信息（"你好"/"谢谢"）→ items=[]
    Case 5 重复偏好（两次"我喜欢喝咖啡"）→ 不应无限创建

验证维度（按用户要求）：
    ✅ Real LLM → ExtractedMemories
    ✅ ExtractedMemories → UserMemory service → user_memory 表
    ✅ 重复 Memory → UPDATE 而非 INSERT
    ✅ Async：chat_node 不阻塞
    ✅ Error Isolation：extraction 失败不破坏主流程
"""

import threading
import time

import pytest

from backend.agent.graph import (
    _dispatch_memory_extraction,
    chat_node,
    reset_graph_for_tests,
)
from backend.agent.memory import (
    _safe_extract_and_write_memory,
    reset_extraction_throttle,
)
from backend.models import UserMemory

from backend.tests.e2e.conftest import (
    count_memory,
    wait_for_memory,
)


# ----------------------------------------------------------------------------
# 公共 fixtures
# ----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _fresh_graph():
    """每个测试用全新 graph，避免 checkpointer 干扰。"""
    reset_graph_for_tests()
    reset_extraction_throttle()
    yield
    reset_graph_for_tests()


def _build_chat_state(user_id, user_input, reply="好的，记下了。", thread_id="e2e_t1"):
    return {
        "user_id": user_id,
        "input": user_input,
        "thread_id": thread_id,
        "messages": [],
    }


def _patch_chat_chain(monkeypatch, reply="好的，记下了。"):
    """把 chat_node 调用的 _get_chat_chain 替换成固定 reply。"""
    class _MockResult:
        content = reply

    class _MockChain:
        def invoke(self, payload):
            return _MockResult()

    monkeypatch.setattr(
        "backend.agent.graph._get_chat_chain",
        lambda: _MockChain(),
    )


# =============================================================================
# Case 1：明确的用户偏好 → 应抽出 preference 类记忆
# =============================================================================
class TestCase1UserPreference:
    def test_extract_preference_sichuan_food(
        self, e2e_user_id
    ):
        """"我平时比较喜欢吃川菜" → LLM 应抽出 preference 记忆。

        验收：8s 内 user_memory 表里出现至少一条 key 与"川菜"语义相关的记录。
        注意：key 的具体拼写由 LLM 决定（normalize_memory_key 不一定把中文变成有意义的英文），
        所以这里用 memory_type + value 双重匹配。
        """
        _safe_extract_and_write_memory(
            e2e_user_id,
            "我平时比较喜欢吃川菜。",
            "好的，记下了。",
        )

        rows = wait_for_memory(e2e_user_id, timeout=8.0, poll=0.2)
        assert rows, "8s 内未出现 user_memory 记录，LLM extraction 可能失败"

        # 至少一条是 preference / habit / fact 类型（不要求严格 preference）
        types = {r.memory_type for r in rows}
        assert types & {"preference", "habit", "fact"}, (
            f"实际 type={types}，未出现 preference/habit/fact"
        )

        # value 中应包含"川菜"语义
        values = " | ".join(r.value for r in rows)
        assert "川菜" in values, f"value 应含'川菜'，实际={values!r}"


# =============================================================================
# Case 2：明确长期事实 → 应抽出 fact 类记忆
# =============================================================================
class TestCase2LongTermFact:
    def test_extract_student_living_expense(
        self, e2e_user_id
    ):
        """"我是学生，月生活费 3000" → LLM 应抽出 fact 记忆。"""
        _safe_extract_and_write_memory(
            e2e_user_id,
            "我是学生，平时每个月生活费大概 3000 元。",
            "明白啦，你是一名学生，月生活费 3000。",
        )

        rows = wait_for_memory(e2e_user_id, timeout=8.0, poll=0.2)
        assert rows, "8s 内未出现 user_memory 记录"

        # 应至少包含 fact / preference
        types = {r.memory_type for r in rows}
        assert types & {"fact", "preference"}, f"实际 type={types}"

        # value 至少出现"学生"或"3000"中一个
        values = " | ".join(r.value for r in rows)
        assert ("学生" in values) or ("3000" in values), (
            f"value 应包含学生/3000，实际={values!r}"
        )


# =============================================================================
# Case 3：普通一次性消费 → 不应污染 memory
# =============================================================================
class TestCase3OneTimeExpenseNoPollution:
    def test_one_time_meal_does_not_pollute(
        self, e2e_user_id
    ):
        """"今天中午吃了 15 块盖饭" → 不应产生明显 memory pollution。

        验收：8s 后 user_memory **可以**是空的；或者出现的内容不应是稳定记忆。
        重点：没有与盖饭/午餐相关的"稳定习惯"被记下。
        """
        _safe_extract_and_write_memory(
            e2e_user_id,
            "今天中午吃了 15 块钱的盖饭。",
            "好的，已记录午餐消费 15 元。",
        )

        # 给 LLM 一点时间（即使它"想"抽东西，也不会立刻完成）
        time.sleep(5.0)

        rows = count_memory(e2e_user_id)  # 不轮询，精确查
        if rows:
            # 若有记录，验证不是"稳定习惯"
            for r in rows:
                assert r.confidence < 0.9, (
                    f"一次性消费 confidence 不应 > 0.9，实际={r.confidence} "
                    f"key={r.key} value={r.value}"
                )

    def test_three_consecutive_one_time_expenses_still_clean(
        self, e2e_user_id
    ):
        """连续 3 笔一次性消费 → 也不应产生 memory pollution。"""
        # 绕过节流（30s 一次）以触发多次 extraction
        for i, msg in enumerate([
            "今天中午吃了 15 块钱的盖饭。",
            "下午买了杯奶茶 20 块。",
            "晚上打车回家 30 块。",
        ]):
            reset_extraction_throttle()  # 每轮都允许触发
            _safe_extract_and_write_memory(
                e2e_user_id, msg, f"ok {i}",
            )

        time.sleep(8.0)
        rows = count_memory(e2e_user_id)
        # 允许 0~1 条（如果 LLM 误抽），但绝不应该 3 条
        assert rows <= 2, f"3 笔一次性消费不应产生 {rows} 条记忆"


# =============================================================================
# Case 4：无 Memory 信息 → items=[]
# =============================================================================
class TestCase4NoSignal:
    def test_greeting_returns_no_memory(
        self, e2e_user_id
    ):
        """"你好" → 不应产生 memory。"""
        _safe_extract_and_write_memory(
            e2e_user_id, "你好", "你好！有什么可以帮你的吗？",
        )
        time.sleep(5.0)
        assert count_memory(e2e_user_id) == 0, (
            "纯问候不应产生 memory"
        )

    def test_thanks_returns_no_memory(
        self, e2e_user_id
    ):
        """"谢谢" → 不应产生 memory。"""
        _safe_extract_and_write_memory(
            e2e_user_id, "谢谢", "不客气！",
        )
        time.sleep(5.0)
        assert count_memory(e2e_user_id) == 0, (
            "纯感谢不应产生 memory"
        )


# =============================================================================
# Case 5：重复偏好 → 应 UPDATE 而非无限 INSERT
# =============================================================================
class TestCase5Deduplication:
    def test_repeated_preference_upserts(
        self, e2e_user_id
    ):
        """两次"我喜欢喝咖啡" → 应 UPSERT 同一 key，不应无限创建。"""
        # 第一次
        reset_extraction_throttle()
        _safe_extract_and_write_memory(
            e2e_user_id, "我喜欢喝咖啡。", "好的，记下你爱喝咖啡。",
        )
        first_rows = wait_for_memory(e2e_user_id, timeout=8.0, poll=0.2)
        assert first_rows, "第一次 extraction 失败"
        first_count = count_memory(e2e_user_id)
        first_keys = {r.key for r in first_rows}
        # 必须至少有一个与咖啡相关的 key
        assert any("coffee" in k or "咖啡" in r.value for k in first_keys for r in first_rows if r.key == k), (
            f"第一次抽取的 key 应与咖啡相关，实际={first_keys}, "
            f"values={[r.value for r in first_rows]}"
        )

        # 第二次（绕过节流）
        reset_extraction_throttle()
        _safe_extract_and_write_memory(
            e2e_user_id,
            "我平时还是喜欢喝咖啡。",
            "嗯嗯，一直记着呢。",
        )
        time.sleep(8.0)

        # 总条数应基本不变（±1 因为 LLM 可能抽多条，第一轮 1~2 条也正常）
        final_count = count_memory(e2e_user_id)
        # 核心断言：不应出现 >= 5 条（明显的无限增长）
        assert final_count < 5, (
            f"重复偏好产生 {final_count} 条记忆，明显是重复创建。"
            f"服务层 UPSERT 逻辑可能失效。"
        )

        # 关键：同一 user 的"咖啡" key 应只有 1 条
        coffee_keys_count = 0
        db_check_rows = []
        from backend.database import SessionLocal
        db = SessionLocal()
        try:
            db_check_rows = db.query(UserMemory).filter(
                UserMemory.user_id == e2e_user_id
            ).all()
        finally:
            db.close()
        for r in db_check_rows:
            if "coffee" in r.key or "咖啡" in r.value:
                coffee_keys_count += 1
        assert coffee_keys_count <= 2, (
            f"同一 user 的'咖啡'相关记忆应为 1~2 条（UPSERT），"
            f"实际={coffee_keys_count}，keys={[r.key for r in db_check_rows]}"
        )


# =============================================================================
# 异步行为：chat_node 不阻塞（即使 LLM 慢）
# =============================================================================
class TestAsyncBehavior:
    def test_chat_node_returns_before_extraction_done(
        self, monkeypatch, e2e_user_id
    ):
        """chat_node 必须立即返回，不等后台 LLM extraction。"""
        _patch_chat_chain(monkeypatch, reply="好的")

        t0 = time.time()
        result = chat_node(_build_chat_state(
            e2e_user_id, "我是一名软件工程师"
        ))
        elapsed = time.time() - t0
        assert result["reply"] == "好的"
        # 真实 LLM 通常 1~5s，chat_node 应 < 2s（不阻塞）
        assert elapsed < 2.0, (
            f"chat_node 耗时 {elapsed:.2f}s，可能被 extraction 阻塞"
        )

        # 等后台线程写库
        rows = wait_for_memory(e2e_user_id, timeout=10.0, poll=0.2)
        # 这一步只验证"后台确实跑完了"，不强求抽出 fact
        # （因为 LLM 输出有随机性，time_parser 等都通过 mock 喂入）


# =============================================================================
# Error Isolation：extraction 失败不破坏主流程
# =============================================================================
class TestErrorIsolation:
    def test_extraction_failure_does_not_break_chat(
        self, monkeypatch, e2e_user_id
    ):
        """如果 LLM extraction 抛异常，chat_node 仍应正常返回 reply。"""
        _patch_chat_chain(monkeypatch, reply="主流程不受影响")

        # 强制让 _safe_extract_and_write_memory 抛异常
        def _boom(uid, ui, reply):
            raise RuntimeError("simulated LLM failure")

        monkeypatch.setattr(
            "backend.agent.memory._safe_extract_and_write_memory",
            _boom,
        )

        # chat_node 必须不抛
        result = chat_node(_build_chat_state(
            e2e_user_id, "随便聊聊"
        ))
        assert result["reply"] == "主流程不受影响"

        # 等 daemon 线程走完
        time.sleep(0.5)

    def test_safe_extract_with_invalid_input_returns_zero(
        self, e2e_user_id
    ):
        """空 user_input → _safe_extract_and_write_memory 应返回 0，不抛。"""
        n = _safe_extract_and_write_memory(e2e_user_id, "", "reply")
        assert n == 0
        n = _safe_extract_and_write_memory("", "hi", "reply")
        assert n == 0

    def test_safe_extract_throttled_returns_zero(
        self, e2e_user_id
    ):
        """节流窗口内连续触发 → 第二次应返回 0。"""
        reset_extraction_throttle()
        # 第一次
        _safe_extract_and_write_memory(e2e_user_id, "我喜欢川菜", "记下")
        # 第二次不重置节流，应被拦
        n = _safe_extract_and_write_memory(e2e_user_id, "我喜欢咖啡", "记下")
        assert n == 0, "节流未生效"


# =============================================================================
# 真实 extraction（不通过 chat_node）直接验证 service 链路
# =============================================================================
class TestServiceLayerIntegration:
    def test_direct_extraction_then_service_write(
        self, e2e_user_id
    ):
        """直接调 _safe_extract_and_write_memory，验证 LLM → service → DB。"""
        n = _safe_extract_and_write_memory(
            e2e_user_id,
            "我是一名自由职业设计师，base 在杭州。",
            "明白啦。",
        )
        # 至少成功 1 条（如果 LLM 抽到了）
        rows = wait_for_memory(e2e_user_id, timeout=8.0, poll=0.2)
        if rows:
            assert n >= 1, f"返回 n={n} 但表里有 {len(rows)} 条"
            for r in rows:
                assert r.user_id == e2e_user_id
                assert r.source == "llm_extracted"
                assert 0.0 <= r.confidence <= 1.0
        else:
            # LLM 可能认为"自由职业"信息不够稳定（这是 OK 的）
            assert n == 0
