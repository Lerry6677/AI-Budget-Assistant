"""L3-7：LangGraph 5 节点图结构契约测试。

目的：
    - 锁住"图必须是 5 个业务节点 + 1 个 intent_node 入口 + 1 个 END"
    - 锁住"图名 = budget_agent_v1"（防止未来重构无声息改结构）
    - 锁住"5 个业务节点各司其职"（断言每个 node 都能被 invoke）

这些测试不是为了测功能（功能 L3-1~L3-6 已覆盖），而是为了"防回退"：
    一旦有人误删一个 node / 改条件边路径，contract 测试会先于功能测试爆掉。
"""

from backend.agent.graph import (
    analyze_node,
    budget_node,
    chat_node,
    expense_node,
    intent_node,
    query_node,
    reset_graph_for_tests,
    get_graph,
)
from backend.agent.state import AgentState


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------
import pytest


@pytest.fixture(autouse=True)
def _fresh_graph():
    """每个测试用全新图（无 checkpointer），避免 SqliteSaver 干扰 contract 断言。"""
    reset_graph_for_tests()
    yield
    reset_graph_for_tests()


def _graph():
    return get_graph()


# ----------------------------------------------------------------------------
# 1. 结构契约：节点名集合固定
# ----------------------------------------------------------------------------
def test_graph_has_exactly_six_nodes():
    """5 业务节点 + 1 个意图路由节点（intent_node）。"""
    g = _graph()
    nodes = g.get_graph().nodes
    # LangGraph 内部还会注入 __start__ / END 等虚拟节点，业务节点固定 6 个
    expected_business_nodes = {
        "intent_node",
        "expense_node",
        "query_node",
        "analyze_node",
        "budget_node",
        "chat_node",
    }
    actual_node_names = set(nodes.keys())
    # 业务节点必须全在
    assert expected_business_nodes.issubset(actual_node_names), (
        f"业务节点缺失：\n"
        f"  expected ⊆ actual\n"
        f"  expected = {sorted(expected_business_nodes)}\n"
        f"  actual   = {sorted(actual_node_names)}"
    )
    # 不能多出"业务节点"（LangGraph 内部 __start__ / __end__ 是允许的，但不允许有人加了 summarize_node / retrieve_node 之类）
    business_only = actual_node_names - {"__start__", "__end__"}
    assert business_only == expected_business_nodes, (
        f"图结构变更！多出或少了节点：\n"
        f"  actual_business = {sorted(business_only)}\n"
        f"  expected        = {sorted(expected_business_nodes)}"
    )


# ----------------------------------------------------------------------------
# 2. 图名契约
# ----------------------------------------------------------------------------
def test_graph_name_is_budget_agent_v1():
    g = _graph()
    # LangGraph 0.2+: CompiledGraph.name 属性
    assert g.name == "budget_agent_v1", (
        f"图名变更！当前 = {g.name!r}，contract 要求 'budget_agent_v1'。"
        "如果是有意升级图版本，请同步更新本 contract。"
    )


# ----------------------------------------------------------------------------
# 3. Node 函数契约：每个 node 都是 callable，且是 module-level 函数（不是 lambda）
# ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "node_fn",
    [intent_node, expense_node, query_node, analyze_node, budget_node, chat_node],
    ids=["intent", "expense", "query", "analyze", "budget", "chat"],
)
def test_node_is_callable_module_function(node_fn):
    """每个 node 必须是 module-level callable，方便 LangGraph 用名字查。"""
    import inspect
    assert callable(node_fn)
    # module-level 函数才有 __module__ + __qualname__
    assert hasattr(node_fn, "__module__")
    assert hasattr(node_fn, "__qualname__")
    # 不能是 lambda（lambda 没有 __qualname__）
    assert "<lambda>" not in node_fn.__qualname__


# ----------------------------------------------------------------------------
# 4. 路由契约：intent_node 必须能把 5 类意图路由到对应节点
# ----------------------------------------------------------------------------
def test_route_after_intent_returns_correct_node_names():
    """_route_after_intent 是条件边的核心。返回的字符串必须与节点名严格一致。"""
    from backend.agent.graph import _route_after_intent

    sample_state: AgentState = {"user_id": "1", "input": "x", "thread_id": "t1"}

    for intent, expected in [
        ("expense", "expense"),
        ("query", "query"),
        ("analyze", "analyze"),
        ("budget", "budget"),
        ("chat", "chat"),
    ]:
        s = {**sample_state, "intent": intent}
        assert _route_after_intent(s) == expected, (
            f"intent={intent} 路由错误：期望 {expected}，实际 {_route_after_intent(s)}"
        )


def test_route_after_intent_falls_back_to_end_for_unknown():
    """未识别的 intent → END（防御兜底，不让图卡住）。"""
    from backend.agent.graph import _route_after_intent
    from langgraph.graph import END

    s: AgentState = {"user_id": "1", "input": "x", "thread_id": "t1", "intent": "weird_intent"}
    assert _route_after_intent(s) == END


# ----------------------------------------------------------------------------
# 5. 入口契约：run_agent 是模块对外唯一接口
# ----------------------------------------------------------------------------
def test_run_agent_is_public_entrypoint():
    """__init__.py 通过 PEP 562 __getattr__ 暴露 run_agent。"""
    import backend.agent as agent_pkg

    assert hasattr(agent_pkg, "run_agent"), (
        "backend.agent 必须导出 run_agent 作为对外入口"
    )
    # 老 L2 接口不应再被默认导出（保留仅作内部 module-level 函数）
    assert not hasattr(agent_pkg, "build_agent"), (
        "build_agent 是 L2 老接口，不应再从 backend.agent 顶层导出"
    )
    assert not hasattr(agent_pkg, "chat_with_agent"), (
        "chat_with_agent 是 L2 老接口，不应再从 backend.agent 顶层导出"
    )