"""RAG 雏形：基于 TF-IDF 的历史问答检索（L3-5 / L3-6）。

目的：
    让"闲聊"节点（chat_node）能复用过去用户问过 / Agent 答过的相似问答对，
    把"短期 LangGraph 内存 messages"扩展为"长期可检索的对话记忆"。

架构（最小化）：
    索引 = sklearn TfidfVectorizer + cosine_similarity
    存储 = SQLite `chat_history` 表（已建好）
    检索范围 = L3-5: 当前 user_id + 当前 thread_id
              L3-6: 当前 user_id + 跨 thread（exclude 当前 thread 防止自召回）
    触发点 = chat_node 完成后；消费点 = chat_node 内部（拼 prompt）

不做的（留 L3-6+ / P3）：
    - embedding 向量库（chroma / faiss / sentence-transformers）
    - 文档 chunking（问答对已经是原子）
    - 自动摘要
    - 检索重排序（rerank）

API（这是模块的对外契约）：
    save_chat(user_id, thread_id, user_input, agent_reply) -> None
    retrieve_similar(user_id, thread_id, query, top_k=3) -> list[dict]
    build_rag_prompt_section(user_id, thread_id, query, top_k=3) -> str
    # L3-6 新增：
    retrieve_similar_cross_thread(user_id, query, top_k=5,
                                  exclude_thread_id=None) -> list[dict]
    build_rag_prompt_section_cross_thread(user_id, query, top_k=5,
                                          exclude_thread_id=None,
                                          current_thread_id=None) -> str
"""

from __future__ import annotations

import threading
from typing import List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from backend.database import SessionLocal
from backend.models import ChatHistory


# ----------------------------------------------------------------------------
# 持久化：把 chat_node 完成的问答对写进 chat_history
# ----------------------------------------------------------------------------
def save_chat(
    user_id: str,
    thread_id: str,
    user_input: str,
    agent_reply: str,
) -> int:
    """保存一条问答对到 chat_history。

    Returns:
        写入的 ChatHistory.id；-1 表示跳过（无 user_id / 输入空）。
    """
    if not user_id or not user_input:
        return -1
    db = SessionLocal()
    try:
        row = ChatHistory(
            user_id=user_id,
            thread_id=thread_id or f"anon_{user_id}",
            user_input=user_input,
            agent_reply=agent_reply or "",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


# ----------------------------------------------------------------------------
# 检索：TF-IDF 索引 + cosine 相似
# ----------------------------------------------------------------------------
def _fetch_thread_history(user_id: str, thread_id: str) -> List[dict]:
    """从 chat_history 拉当前 user_id + thread_id 的所有问答对（按时间升序）。"""
    db = SessionLocal()
    try:
        rows = (
            db.query(ChatHistory)
            .filter(ChatHistory.user_id == user_id)
            .filter(ChatHistory.thread_id == thread_id)
            .order_by(ChatHistory.created_at.asc())
            .all()
        )
        return [
            {
                "id": r.id,
                "user_input": r.user_input,
                "agent_reply": r.agent_reply,
            }
            for r in rows
        ]
    finally:
        db.close()


# sklearn 是无状态的，Vectorizer 可以在每次检索里临时建，不缓存。
# 但 Vectorizer.fit_transform 在大量历史时会重复计算 → 这里用"懒建"：
# 只在 retrieve_similar 里 build 一次（调用方并发安全由 GIL + 局部变量保证）。
def retrieve_similar(
    user_id: str,
    thread_id: str,
    query: str,
    top_k: int = 3,
    min_similarity: float = 0.05,
) -> List[dict]:
    """检索当前 thread 内与 query 最相似的 top_k 条历史问答。

    Args:
        user_id:        必填，强制隔离
        thread_id:      必填，限定在单 thread 内
        query:          用户当前输入
        top_k:          返回条数
        min_similarity: 低于此相似度丢弃（避免噪音）；默认 0.05（极宽松）

    Returns:
        list[{user_input, agent_reply, similarity}]，按相似度降序
    """
    if not user_id or not query:
        return []
    history = _fetch_thread_history(user_id, thread_id)
    if not history:
        return []

    corpus = [h["user_input"] for h in history]
    corpus.append(query)  # 最后一个是 query
    try:
        vectorizer = TfidfVectorizer(
            analyzer="char_wb",  # 中英文都凑合
            ngram_range=(2, 4),
            min_df=1,
        )
        tfidf = vectorizer.fit_transform(corpus)
    except ValueError:
        # 语料全空 / 全 1 词 → fit 失败，返回空
        return []

    query_vec = tfidf[-1]
    history_vecs = tfidf[:-1]
    if history_vecs.shape[0] == 0:
        return []
    sims = cosine_similarity(query_vec, history_vecs).flatten()

    ranked = sorted(
        zip(sims, history),
        key=lambda x: x[0],
        reverse=True,
    )
    results = []
    for sim, h in ranked[:top_k]:
        if sim < min_similarity:
            continue
        results.append({
            "user_input": h["user_input"],
            "agent_reply": h["agent_reply"],
            "similarity": float(sim),
        })
    return results


# ----------------------------------------------------------------------------
# Prompt 组装：把检索结果拼成 LLM 看得懂的段落
# ----------------------------------------------------------------------------
def build_rag_prompt_section(
    user_id: str,
    thread_id: str,
    query: str,
    top_k: int = 3,
) -> str:
    """检索 + 拼成 RAG 段落。

    段落格式（可直接拼到 LLM system prompt）：
        <history>
        1. [用户] xxx
           [回答] yyy
        2. ...
        </history>

    无历史时返回空串（调用方决定是否插入）。
    """
    hits = retrieve_similar(user_id, thread_id, query, top_k=top_k)
    if not hits:
        return ""
    lines = ["<history>"]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. [用户] {h['user_input']}")
        lines.append(f"   [回答] {h['agent_reply']}")
    lines.append("</history>")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# L3-6：跨 thread 检索（同 user，其他会话的长期记忆）
# ----------------------------------------------------------------------------
def _fetch_user_history(user_id: str) -> List[dict]:
    """从 chat_history 拉当前 user_id 的所有问答对（跨 thread，按时间升序）。

    L3-6 新增：跨 thread 检索用。thread 字段一并返回，prompt 里可标注来源。
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(ChatHistory)
            .filter(ChatHistory.user_id == user_id)
            .order_by(ChatHistory.created_at.asc())
            .all()
        )
        return [
            {
                "id": r.id,
                "user_input": r.user_input,
                "agent_reply": r.agent_reply,
                "thread_id": r.thread_id,
            }
            for r in rows
        ]
    finally:
        db.close()


def retrieve_similar_cross_thread(
    user_id: str,
    query: str,
    top_k: int = 5,
    min_similarity: float = 0.05,
    exclude_thread_id: Optional[str] = None,
) -> List[dict]:
    """跨 thread 检索（同一 user 的所有历史问答对里找相似）。

    与 retrieve_similar 的区别：
        - 不按 thread 过滤
        - 默认 exclude_thread_id=当前 thread（chat_node 调用时传），
          防止"刚写的历史"立刻被自己召回造成噪声循环。
        - top_k 默认 5（更多上下文，但靠 min_similarity + rerank-by-LLM 控制质量）

    Args:
        user_id:           必填，强制隔离
        query:             用户当前输入
        top_k:             返回条数（默认 5）
        min_similarity:    低于此相似度丢弃（避免噪音）；默认 0.05
        exclude_thread_id: 排除的 thread（通常传"当前 thread"避免自召回）

    Returns:
        list[{user_input, agent_reply, similarity, thread_id}]，按相似度降序
    """
    if not user_id or not query:
        return []
    history = _fetch_user_history(user_id)
    if not history:
        return []

    # 排除指定 thread
    if exclude_thread_id:
        history = [h for h in history if h["thread_id"] != exclude_thread_id]
    if not history:
        return []

    corpus = [h["user_input"] for h in history]
    corpus.append(query)  # 最后一个是 query
    try:
        vectorizer = TfidfVectorizer(
            analyzer="char_wb",  # 中英文都凑合
            ngram_range=(2, 4),
            min_df=1,
        )
        tfidf = vectorizer.fit_transform(corpus)
    except ValueError:
        return []

    query_vec = tfidf[-1]
    history_vecs = tfidf[:-1]
    if history_vecs.shape[0] == 0:
        return []
    sims = cosine_similarity(query_vec, history_vecs).flatten()

    ranked = sorted(
        zip(sims, history),
        key=lambda x: x[0],
        reverse=True,
    )
    results = []
    for sim, h in ranked[:top_k]:
        if sim < min_similarity:
            continue
        results.append({
            "user_input": h["user_input"],
            "agent_reply": h["agent_reply"],
            "similarity": float(sim),
            "thread_id": h["thread_id"],
        })
    return results


def build_rag_prompt_section_cross_thread(
    user_id: str,
    query: str,
    top_k: int = 5,
    exclude_thread_id: Optional[str] = None,
    current_thread_id: Optional[str] = None,
    min_similarity: float = 0.05,
) -> str:
    """跨 thread 检索 + 拼 RAG 段落（L3-6 新增）。

    段落格式（与单 thread 版略有不同，标注来源 thread 让 LLM 知道是历史会话）：
        <history cross_thread=true>
        1. [用户/thread:abc] xxx
           [回答] yyy
        2. ...
        </history>

    无历史时返回空串。
    """
    hits = retrieve_similar_cross_thread(
        user_id=user_id,
        query=query,
        top_k=top_k,
        min_similarity=min_similarity,
        exclude_thread_id=exclude_thread_id,
    )
    if not hits:
        return ""
    lines = ["<history cross_thread=true>"]
    for i, h in enumerate(hits, 1):
        # 标注：方便 LLM 判断"这是另一会话的历史，不是当前上下文"
        tag = f"thread:{h['thread_id']}"
        if current_thread_id and h["thread_id"] == current_thread_id:
            tag = "thread:current"
        lines.append(f"{i}. [用户/{tag}] {h['user_input']}")
        lines.append(f"   [回答] {h['agent_reply']}")
    lines.append("</history>")
    return "\n".join(lines)


__all__ = [
    "save_chat",
    "retrieve_similar",
    "build_rag_prompt_section",
    "retrieve_similar_cross_thread",
    "build_rag_prompt_section_cross_thread",
]