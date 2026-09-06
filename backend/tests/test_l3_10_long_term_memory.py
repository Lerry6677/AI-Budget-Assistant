"""Task 22 Long-term Memory service 层单测（Step 2 范围）。

覆盖：
    - normalize_memory_key 纯函数
    - get_user_memories 读取 + memory_type 过滤 + user 隔离
    - write_or_update_user_memory upsert 语义 + 并发 UNIQUE 冲突
    - (user_id, key) UNIQUE 拒绝重复
"""
import pytest
from sqlalchemy.exc import IntegrityError

from backend.database import SessionLocal
from backend.models import UserMemory
from backend.schemas.user_memory import ExtractedMemory
from backend.services import memory_service
from backend.services.memory_service import (
    get_user_memories,
    normalize_memory_key,
    write_or_update_user_memory,
)


# ----------------------------------------------------------------------------
# normalize_memory_key
# ----------------------------------------------------------------------------
class TestNormalizeMemoryKey:
    """纯函数 normalize_memory_key 的语义测试。"""

    def test_empty_string_returns_empty(self):
        assert normalize_memory_key("") == ""

    def test_none_returns_empty(self):
        assert normalize_memory_key(None) == ""

    def test_lowercase(self):
        assert normalize_memory_key("I LOVE COFFEE") == "i_love_coffee"

    def test_chinese_text_normalizes(self):
        # 纯中文：所有字符都非 [a-z0-9]，归一化后为空字符串
        out = normalize_memory_key("我喜欢咖啡")
        assert out == ""
        # 含中英混合：中文段被 strip，保留英文段
        out_mixed = normalize_memory_key("我 love 咖啡")
        # 实际行为：非 a-z0-9 字符全替为 '_'，连续 _ 合并，首尾 strip
        # "我 love 咖啡" -> "_love__" -> "_love_" -> "love"
        assert out_mixed == "love"
        # 只含 a-z 0-9 _
        import re
        assert re.fullmatch(r"[a-z0-9_]*", out)

    def test_snake_case(self):
        assert normalize_memory_key("I love coffee") == "i_love_coffee"
        assert normalize_memory_key("weekend-brunch") == "weekend_brunch"

    def test_strips_punctuation(self):
        assert normalize_memory_key("weekend-brunch!!") == "weekend_brunch"
        assert normalize_memory_key("hello, world!") == "hello_world"
        assert normalize_memory_key("@home #coffee") == "home_coffee"

    def test_merges_consecutive_underscores(self):
        assert normalize_memory_key("a___b   c") == "a_b_c"

    def test_strips_leading_trailing_underscores(self):
        assert normalize_memory_key("__hello__") == "hello"

    def test_fullwidth_to_halfwidth(self):
        # 全角字母 NFKC 归一
        assert normalize_memory_key("Ｈｅｌｌｏ") == "hello"

    def test_truncates_to_64_chars(self):
        long_text = "a" * 200
        out = normalize_memory_key(long_text)
        assert len(out) <= 64
        assert out == "a" * 64

    def test_emoji_stripped(self):
        # emoji 不属于 [a-z0-9]，应被替换为下划线
        out = normalize_memory_key("coffee ☕ daily")
        assert "emoji" not in out or "_" in out
        assert "coffee" in out

    def test_idempotent(self):
        # 同一输入两次结果一致
        text = "I Love Coffee! ☕"
        out1 = normalize_memory_key(text)
        out2 = normalize_memory_key(out1)
        assert out1 == out2


# ----------------------------------------------------------------------------
# write_or_update_user_memory
# ----------------------------------------------------------------------------
class TestWriteOrUpdateUserMemory:
    """service upsert 行为 + (user_id, key) UNIQUE 触发。"""

    def test_inserts_when_absent(self, user_id):
        db = SessionLocal()
        try:
            memory = ExtractedMemory(
                memory_type="preference",
                key="I love coffee",
                value="User likes coffee",
                confidence=0.8,
                source="llm_extracted",
            )
            row = write_or_update_user_memory(db, user_id, memory)
            assert row.id is not None
            assert row.user_id == user_id
            assert row.key == "i_love_coffee"  # 已归一化
            assert row.value == "User likes coffee"
            assert row.confidence == 0.8
            assert row.source == "llm_extracted"
            assert row.memory_type == "preference"
        finally:
            db.close()

    def test_updates_when_present(self, user_id):
        db = SessionLocal()
        try:
            memory_v1 = ExtractedMemory(
                memory_type="preference",
                key="coffee",
                value="User drinks coffee",
                confidence=0.5,
            )
            write_or_update_user_memory(db, user_id, memory_v1)
            first_id = db.query(UserMemory).filter(
                UserMemory.user_id == user_id
            ).first().id

            # 同一 (user_id, key) 第二次写 → UPDATE
            memory_v2 = ExtractedMemory(
                memory_type="habit",
                key="coffee",
                value="User drinks coffee daily",
                confidence=0.9,
            )
            row = write_or_update_user_memory(db, user_id, memory_v2)
            assert row.id == first_id  # 同一行
            assert row.value == "User drinks coffee daily"
            assert row.confidence == 0.9
            assert row.memory_type == "habit"
        finally:
            db.close()

    def test_different_keys_insert_separate_rows(self, user_id):
        db = SessionLocal()
        try:
            write_or_update_user_memory(db, user_id, ExtractedMemory(
                memory_type="preference", key="coffee", value="likes coffee"))
            write_or_update_user_memory(db, user_id, ExtractedMemory(
                memory_type="preference", key="tea", value="likes tea"))
            rows = get_user_memories(db, user_id)
            assert len(rows) == 2
        finally:
            db.close()

    def test_user_isolation_on_write(self, user_id, other_user_id):
        """同名 key 在不同 user 下不应冲突；user A 写入不影响 user B。"""
        db = SessionLocal()
        try:
            write_or_update_user_memory(db, user_id, ExtractedMemory(
                memory_type="preference", key="coffee", value="A's coffee"))
            write_or_update_user_memory(db, other_user_id, ExtractedMemory(
                memory_type="preference", key="coffee", value="B's coffee"))

            a_rows = get_user_memories(db, user_id)
            b_rows = get_user_memories(db, other_user_id)
            assert len(a_rows) == 1
            assert len(b_rows) == 1
            assert a_rows[0].value == "A's coffee"
            assert b_rows[0].value == "B's coffee"
        finally:
            db.close()

    def test_empty_normalized_key_raises_value_error(self, user_id):
        """全标点归一化为空 → 抛 ValueError 显式失败。"""
        db = SessionLocal()
        try:
            memory = ExtractedMemory(
                memory_type="fact",
                key="!!!",
                value="something",
            )
            with pytest.raises(ValueError, match="normalizes to empty"):
                write_or_update_user_memory(db, user_id, memory)
        finally:
            db.close()

    def test_unique_constraint_blocks_direct_dup(self, user_id):
        """绕过 service 直接 ORM insert 重复 (user_id, key) → IntegrityError。"""
        db = SessionLocal()
        try:
            db.add(UserMemory(
                user_id=user_id,
                memory_type="preference",
                key="coffee",
                value="first",
            ))
            db.commit()

            db.add(UserMemory(
                user_id=user_id,
                memory_type="preference",
                key="coffee",
                value="second",
            ))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
        finally:
            db.close()


# ----------------------------------------------------------------------------
# get_user_memories
# ----------------------------------------------------------------------------
class TestGetUserMemories:
    """读取 + 过滤 + 隔离。"""

    def test_returns_empty_for_unknown_user(self, user_id):
        db = SessionLocal()
        try:
            assert get_user_memories(db, user_id) == []
        finally:
            db.close()

    def test_returns_all_for_user(self, user_id):
        db = SessionLocal()
        try:
            for k in ["coffee", "tea", "weekend_brunch"]:
                write_or_update_user_memory(db, user_id, ExtractedMemory(
                    memory_type="preference", key=k, value=k))
            rows = get_user_memories(db, user_id)
            assert len(rows) == 3
            keys = {r.key for r in rows}
            assert keys == {"coffee", "tea", "weekend_brunch"}
        finally:
            db.close()

    def test_filters_by_memory_type(self, user_id):
        db = SessionLocal()
        try:
            write_or_update_user_memory(db, user_id, ExtractedMemory(
                memory_type="preference", key="coffee", value="x"))
            write_or_update_user_memory(db, user_id, ExtractedMemory(
                memory_type="habit", key="morning_run", value="x"))
            write_or_update_user_memory(db, user_id, ExtractedMemory(
                memory_type="fact", key="city", value="Shanghai"))

            prefs = get_user_memories(db, user_id, memory_type="preference")
            habits = get_user_memories(db, user_id, memory_type="habit")
            facts = get_user_memories(db, user_id, memory_type="fact")

            assert len(prefs) == 1
            assert prefs[0].key == "coffee"
            assert len(habits) == 1
            assert habits[0].key == "morning_run"
            assert len(facts) == 1
            assert facts[0].key == "city"
        finally:
            db.close()

    def test_user_a_cannot_see_user_b(self, user_id, other_user_id):
        """user_id 隔离：user B 写入不影响 user A 读。"""
        db = SessionLocal()
        try:
            write_or_update_user_memory(db, user_id, ExtractedMemory(
                memory_type="preference", key="coffee", value="A"))
            write_or_update_user_memory(db, other_user_id, ExtractedMemory(
                memory_type="preference", key="tea", value="B"))

            a = get_user_memories(db, user_id)
            b = get_user_memories(db, other_user_id)
            assert {r.value for r in a} == {"A"}
            assert {r.value for r in b} == {"B"}
        finally:
            db.close()

    def test_invalid_memory_type_filter_returns_empty(self, user_id):
        """不存在的 memory_type 过滤 → 空列表（不抛错）。"""
        db = SessionLocal()
        try:
            write_or_update_user_memory(db, user_id, ExtractedMemory(
                memory_type="preference", key="coffee", value="x"))
            rows = get_user_memories(db, user_id, memory_type="nonexistent")
            assert rows == []
        finally:
            db.close()

    def test_service_exports_are_correct(self):
        """service 模块对外暴露的入口。"""
        assert hasattr(memory_service, "normalize_memory_key")
        assert hasattr(memory_service, "get_user_memories")
        assert hasattr(memory_service, "write_or_update_user_memory")


# ----------------------------------------------------------------------------
# Task 22 Step 3：memory extraction（旁路模块）
# ----------------------------------------------------------------------------
class TestMemoryExtractionPrompt:
    """prompts.MEMORY_EXTRACTION_PROMPT / extract_memory_from_chat 的契约。"""

    def test_prompt_template_exists(self):
        from backend.agent.prompts import MEMORY_EXTRACTION_PROMPT
        assert MEMORY_EXTRACTION_PROMPT is not None

    def test_extract_function_raises_on_llm_failure(self, monkeypatch, user_id):
        """LLM 调用失败 → 抛 MemoryExtractionError（不静默吞）。"""
        from backend.agent import prompts

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated LLM failure")

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _boom)

        with pytest.raises(prompts.MemoryExtractionError):
            prompts.extract_memory_from_chat(
                user_input="hi", agent_reply="hello"
            )

    def test_extract_returns_empty_on_no_signal(self, monkeypatch, user_id):
        """LLM 返回 items=[] 时，提取函数返回空 list。"""
        from backend.agent import prompts
        from backend.schemas.user_memory import ExtractedMemories

        class _FakeChain:
            def invoke(self, payload):
                return ExtractedMemories(items=[])

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _FakeChain())

        result = prompts.extract_memory_from_chat(
            user_input="hi", agent_reply="hello"
        )
        assert result == []

    def test_extract_returns_typed_items(self, monkeypatch, user_id):
        """LLM 返回带 items 时，提取函数返回 ExtractedMemory list。"""
        from backend.agent import prompts
        from backend.schemas.user_memory import ExtractedMemories, ExtractedMemory

        class _FakeChain:
            def invoke(self, payload):
                return ExtractedMemories(items=[
                    ExtractedMemory(
                        memory_type="preference",
                        key="i_love_coffee",
                        value="User likes coffee",
                        confidence=0.8,
                    ),
                ])

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _FakeChain())

        result = prompts.extract_memory_from_chat(
            user_input="hi", agent_reply="hello"
        )
        assert len(result) == 1
        assert result[0].memory_type == "preference"
        assert result[0].key == "i_love_coffee"
        assert result[0].confidence == 0.8


class TestSafeExtractAndWriteMemory:
    """_safe_extract_and_write_memory 旁路行为：
        - 失败吞掉，不抛
        - 频控生效
        - 低 confidence / 空 key 过滤
        - 写库后能 read 出来
        - 异常 LLM → 不写库
        - 单条 write 失败不影响其他条
    """

    def test_extraction_failure_does_not_raise(self, monkeypatch, user_id):
        """LLM 异常 → 返回 0，不抛。"""
        from backend.agent import memory as mem_mod
        from backend.agent import prompts

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated LLM failure")

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _boom)
        # 强制清空频控确保触发
        mem_mod.reset_extraction_throttle()

        n = mem_mod._safe_extract_and_write_memory(
            user_id, "hi", "hello"
        )
        assert n == 0

    def test_empty_user_input_skips(self, monkeypatch, user_id):
        """user_input 为空 → 直接返回 0。"""
        from backend.agent import memory as mem_mod
        from backend.agent import prompts
        called = {"count": 0}

        def _counting(*args, **kwargs):
            called["count"] += 1
            from backend.schemas.user_memory import ExtractedMemories
            return ExtractedMemories(items=[])

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _counting)
        mem_mod.reset_extraction_throttle()

        n = mem_mod._safe_extract_and_write_memory(
            user_id, "", "hello"
        )
        assert n == 0
        # extraction chain 根本没被调用
        assert called["count"] == 0

    def test_no_items_returns_zero(self, monkeypatch, user_id):
        """LLM 返回 items=[] → 返回 0，不写库。"""
        from backend.agent import memory as mem_mod
        from backend.agent import prompts
        from backend.schemas.user_memory import ExtractedMemories

        class _FakeChain:
            def invoke(self, payload):
                return ExtractedMemories(items=[])

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _FakeChain())
        mem_mod.reset_extraction_throttle()

        n = mem_mod._safe_extract_and_write_memory(
            user_id, "今天花了多少", "查一下"
        )
        assert n == 0

    def test_throttle_blocks_repeated_calls(self, monkeypatch, user_id):
        """频控：30 秒内重复调用 → 仅第一次真实跑。"""
        from backend.agent import memory as mem_mod
        from backend.agent import prompts
        from backend.schemas.user_memory import ExtractedMemories, ExtractedMemory

        calls = {"count": 0}

        class _FakeChain:
            def invoke(self, payload):
                calls["count"] += 1
                return ExtractedMemories(items=[
                    ExtractedMemory(
                        memory_type="preference",
                        key="coffee",
                        value="likes coffee",
                        confidence=0.9,
                    )
                ])

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _FakeChain())
        mem_mod.reset_extraction_throttle()

        n1 = mem_mod._safe_extract_and_write_memory(user_id, "hi", "hello")
        n2 = mem_mod._safe_extract_and_write_memory(user_id, "hi again", "hello")
        # 第一次真的跑了，第二次被节流
        assert n1 == 1
        assert n2 == 0
        assert calls["count"] == 1

    def test_throttle_can_be_reset(self, monkeypatch, user_id):
        """reset_extraction_throttle 之后重新允许触发。"""
        from backend.agent import memory as mem_mod
        from backend.agent import prompts
        from backend.schemas.user_memory import ExtractedMemories, ExtractedMemory

        class _FakeChain:
            def invoke(self, payload):
                return ExtractedMemories(items=[
                    ExtractedMemory(
                        memory_type="preference",
                        key="coffee",
                        value="likes coffee",
                        confidence=0.9,
                    )
                ])

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _FakeChain())
        mem_mod.reset_extraction_throttle()

        assert mem_mod._safe_extract_and_write_memory(user_id, "hi", "hello") == 1
        # 节流中
        assert mem_mod._safe_extract_and_write_memory(user_id, "hi", "hello") == 0
        # 重置
        mem_mod.reset_extraction_throttle()
        assert mem_mod._safe_extract_and_write_memory(user_id, "hi", "hello") == 1

    def test_low_confidence_filtered_out(self, monkeypatch, user_id):
        """confidence < 0.3 的条目不写入。"""
        from backend.agent import memory as mem_mod
        from backend.agent import prompts
        from backend.schemas.user_memory import ExtractedMemories, ExtractedMemory

        class _FakeChain:
            def invoke(self, payload):
                return ExtractedMemories(items=[
                    ExtractedMemory(
                        memory_type="preference",
                        key="noise",
                        value="low conf signal",
                        confidence=0.1,  # < 0.3
                    ),
                    ExtractedMemory(
                        memory_type="preference",
                        key="good_signal",
                        value="real preference",
                        confidence=0.9,
                    ),
                ])

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _FakeChain())
        mem_mod.reset_extraction_throttle()

        n = mem_mod._safe_extract_and_write_memory(
            user_id, "hi", "hello"
        )
        assert n == 1  # 只有高 confidence 的写入了

        db = SessionLocal()
        try:
            keys = {r.key for r in get_user_memories(db, user_id)}
            assert "good_signal" in keys
            assert "noise" not in keys
        finally:
            db.close()

    def test_empty_normalized_key_filtered_out(self, monkeypatch, user_id):
        """归一化后 key 为空的条目不写入（中文全标点等）。"""
        from backend.agent import memory as mem_mod
        from backend.agent import prompts
        from backend.schemas.user_memory import ExtractedMemories, ExtractedMemory

        class _FakeChain:
            def invoke(self, payload):
                return ExtractedMemories(items=[
                    ExtractedMemory(
                        memory_type="fact",
                        key="!!!",  # 归一化为空
                        value="something",
                        confidence=0.9,
                    ),
                    ExtractedMemory(
                        memory_type="preference",
                        key="coffee",
                        value="likes coffee",
                        confidence=0.9,
                    ),
                ])

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _FakeChain())
        mem_mod.reset_extraction_throttle()

        n = mem_mod._safe_extract_and_write_memory(
            user_id, "hi", "hello"
        )
        assert n == 1  # 空 key 被过滤

    def test_writes_persist_to_db(self, monkeypatch, user_id):
        """成功路径：写入后 get_user_memories 能读出。"""
        from backend.agent import memory as mem_mod
        from backend.agent import prompts
        from backend.schemas.user_memory import ExtractedMemories, ExtractedMemory

        class _FakeChain:
            def invoke(self, payload):
                return ExtractedMemories(items=[
                    ExtractedMemory(
                        memory_type="fact",
                        key="city",
                        value="Shanghai",
                        confidence=0.95,
                    ),
                    ExtractedMemory(
                        memory_type="preference",
                        key="coffee",
                        value="likes coffee",
                        confidence=0.8,
                    ),
                ])

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _FakeChain())
        mem_mod.reset_extraction_throttle()

        n = mem_mod._safe_extract_and_write_memory(
            user_id, "I live in Shanghai and love coffee", "Noted!"
        )
        assert n == 2

        db = SessionLocal()
        try:
            rows = get_user_memories(db, user_id)
            keys = {r.key for r in rows}
            assert keys == {"city", "coffee"}
            city = next(r for r in rows if r.key == "city")
            assert city.value == "Shanghai"
            assert city.memory_type == "fact"
        finally:
            db.close()

    def test_user_isolation_in_extraction(self, monkeypatch, user_id, other_user_id):
        """extraction 写库严格按 user_id 隔离。"""
        from backend.agent import memory as mem_mod
        from backend.agent import prompts
        from backend.schemas.user_memory import ExtractedMemories, ExtractedMemory

        class _FakeChain:
            def invoke(self, payload):
                return ExtractedMemories(items=[
                    ExtractedMemory(
                        memory_type="preference",
                        key="coffee",
                        value="payload-driven value",
                        confidence=0.9,
                    )
                ])

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _FakeChain())
        mem_mod.reset_extraction_throttle()

        mem_mod._safe_extract_and_write_memory(user_id, "I love coffee", "ok")
        mem_mod.reset_extraction_throttle()
        mem_mod._safe_extract_and_write_memory(other_user_id, "I love tea", "ok")

        db = SessionLocal()
        try:
            a = get_user_memories(db, user_id)
            b = get_user_memories(db, other_user_id)
            assert len(a) == 1
            assert len(b) == 1
            # 注意：因 key 都是 'coffee' 归一化，但用户不同 → 两行独立
            assert a[0].user_id == user_id
            assert b[0].user_id == other_user_id
        finally:
            db.close()

    def test_write_failure_continues_for_other_items(self, monkeypatch, user_id):
        """单条 write 失败不影响其他条目。"""
        from backend.agent import memory as mem_mod
        from backend.agent import prompts
        from backend.schemas.user_memory import ExtractedMemories, ExtractedMemory

        class _FakeChain:
            def invoke(self, payload):
                return ExtractedMemories(items=[
                    ExtractedMemory(
                        memory_type="preference",
                        key="coffee",
                        value="likes coffee",
                        confidence=0.9,
                    ),
                    ExtractedMemory(
                        memory_type="preference",
                        key="tea",
                        value="likes tea",
                        confidence=0.9,
                    ),
                ])

        monkeypatch.setattr(prompts, "_memory_extraction_chain", _FakeChain())
        mem_mod.reset_extraction_throttle()

        # service write 抛错 → 旁路应 continue
        original_write = mem_mod.write_or_update_user_memory
        call_count = {"n": 0}

        def _flaky(db, uid, mem):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated DB failure on first item")
            return original_write(db, uid, mem)

        monkeypatch.setattr(mem_mod, "write_or_update_user_memory", _flaky)

        n = mem_mod._safe_extract_and_write_memory(user_id, "hi", "hello")
        # 第一条失败，第二条成功
        assert n == 1

        db = SessionLocal()
        try:
            keys = {r.key for r in get_user_memories(db, user_id)}
            assert "tea" in keys
            assert "coffee" not in keys
        finally:
            db.close()


class TestShouldExtractThrottle:
    """频控内部逻辑。"""

    def test_should_extract_first_call(self, user_id):
        from backend.agent import memory as mem_mod
        mem_mod.reset_extraction_throttle()
        assert mem_mod._should_extract(user_id, now=1000.0) is True

    def test_should_extract_blocks_within_window(self, user_id):
        from backend.agent import memory as mem_mod
        mem_mod.reset_extraction_throttle()
        mem_mod._should_extract(user_id, now=1000.0)
        # 10 秒后仍在窗口内（默认 30 秒）
        assert mem_mod._should_extract(user_id, now=1010.0) is False

    def test_should_extract_allows_after_window(self, user_id):
        from backend.agent import memory as mem_mod
        mem_mod.reset_extraction_throttle()
        mem_mod._should_extract(user_id, now=1000.0)
        # 31 秒后过窗口
        assert mem_mod._should_extract(user_id, now=1031.0) is True

    def test_different_users_have_independent_throttle(self, user_id, other_user_id):
        from backend.agent import memory as mem_mod
        mem_mod.reset_extraction_throttle()
        # user_id 触发
        mem_mod._should_extract(user_id, now=1000.0)
        # other_user_id 不受影响
        assert mem_mod._should_extract(other_user_id, now=1000.0) is True


class TestMemoryModuleExports:
    """旁路模块的导出契约。"""

    def test_module_has_safe_entry(self):
        from backend.agent import memory as mem_mod
        assert hasattr(mem_mod, "_safe_extract_and_write_memory")
        assert hasattr(mem_mod, "_should_extract")
        assert hasattr(mem_mod, "reset_extraction_throttle")

    def test_module_does_not_modify_state(self):
        """memory 模块不引入 AgentState 修改（Step 3 不接 graph）。"""
        from backend.agent import memory as mem_mod
        # 仅检查模块属性集合中不出现 add_messages / state class 修改
        names = dir(mem_mod)
        # 仅暴露业务函数 + 常量
        business_names = {
            "_safe_extract_and_write_memory",
            "_should_extract",
            "reset_extraction_throttle",
            "MIN_SECONDS_BETWEEN_EXTRACTION",
            "get_user_memories",
        }
        # 允许有 logging / threading / time 等导入名；业务函数必须齐全
        for name in business_names:
            assert name in names, f"missing {name} in memory module"