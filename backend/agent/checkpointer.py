"""会话记忆 Checkpointer。

LangGraph 通过 checkpointer 在多次 invoke 之间持久化 Agent 状态。
每个 user_id 作为一个 thread_id，互不干扰。

【两种实现】
    1) 内存版（开发用）: from langgraph.checkpoint.memory import MemorySaver
    2) 持久化版（生产推荐）: from langgraph.checkpoint.sqlite import SqliteSaver
                           或 from langgraph.checkpoint.mysql import MySQLSaver

【推荐】
    - 先用 SqliteSaver / 文件，部署到 MySQL 时再切到 MySQLSaver
    - checkpointer 应该是模块级单例（不要每次 build_agent 都新建）
"""

import os

from langgraph.checkpoint.memory import MemorySaver


# 临时默认：内存版，方便本地起步
_checkpointer = MemorySaver()


def get_checkpointer():
    """返回当前进程共享的 checkpointer 单例。

    TODO: 根据环境变量切换：
        if os.getenv("CHECKPOINTER", "memory") == "sqlite":
            from langgraph.checkpoint.sqlite import SqliteSaver
            return SqliteSaver.from_conn_string("checkpoints.db")
        if os.getenv("CHECKPOINTER") == "mysql":
            from langgraph.checkpoint.mysql import MySQLSaver
            ...
    """
    return _checkpointer
