"""RAG 雏形：基于 TF-IDF 的历史问答检索（L3-5 / L3-6 / Task 20）。

目的：
    让"闲聊"节点（chat_node）能复用过去用户问过 / Agent 答过的相似问答对，
    把"短期 LangGraph 内存 messages"扩展为"长期可检索的对话记忆"。

架构（最小化）：
    索引 = sklearn TfidfVectorizer + cosine_similarity
    存储 = SQLite `chat_history` 表（已建好）
    检索范围 = L3-5: 当前 user_id + 当前 thread_id
              L3-6: 当前 user_id + 跨 thread（exclude 当前 thread 防止自召回）
              Task 20: 跨 thread 默认开启 user_input 归一化去重
    触发点 = chat_node 完成后；消费点 = chat_node 内部（拼 prompt）

Task 20 新增（**仅可观测性 + 召回质量**，不改 schema / 不引 embedding）：
    - 模块级 logging：每次 retrieve_*/build_*_*_section_* 输出 hits/avg_sim/max_sim/took_ms
    - RAG_DEFAULT_MIN_SIMILARITY / RAG_DEFAULT_TOP_K 常量，便于测试覆盖
    - retrieve_* / build_*_*_section_* 新增 return_meta=False 参数：
      True 时返回 (result, meta)，meta 含 {hits, avg_sim, max_sim, took_ms, mode, ...}
    - _fetch_*_history 返回 dict 增加 created_at（ISO 字符串），便于排序/可观测性
    - retrieve_similar_cross_thread 默认按 user_input 归一化去重（dedup=True）
    - **不改** similarity 默认阈值（保持 L3-6 的 0.05，留待有真实评测数据再调）
    - **不把** similarity 注入 prompt（避免 LLM 把检索评分当事实依据）

不做的（留 P3）：
    - embedding 向量库（chroma / faiss / sentence-transformers）
    - 文档 chunking（问答对已经是原子）
    - 自动摘要
    - 检索重排序（rerank）
    - BM25 / 关键词权重 / 时间衰减

API（这是模块的对外契约）：
    save_chat(user_id, thread_id, user_input, agent_reply) -> int
    retrieve_similar(user_id, thread_id, query, top_k=3,
                     min_similarity=RAG_DEFAULT_MIN_SIMILARITY,
                     return_meta=False) -> list[dict] | (list[dict], dict)
    build_rag_prompt_section(user_id, thread_id, query, top_k=3,
                             min_similarity=RAG_DEFAULT_MIN_SIMILARITY,
                             return_meta=False) -> str | (str, dict)
    # L3-6 新增：
    retrieve_similar_cross_thread(user_id, query, top_k=RAG_DEFAULT_TOP_K,
                                  min_similarity=RAG_DEFAULT_MIN_SIMILARITY,
                                  exclude_thread_id=None,
                                  dedup=True,
                                  return_meta=False) -> list[dict] | (list[dict], dict)
    build_rag_prompt_section_cross_thread(user_id, query, top_k=RAG_DEFAULT_TOP_K,
                                          exclude_thread_id=None,
                                          current_thread_id=None,
                                          min_similarity=RAG_DEFAULT_MIN_SIMILARITY,
                                          dedup=True,
                                          return_meta=False) -> str | (str, dict)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, List, Optional, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from backend.database import SessionLocal
from backend.models import ChatHistory


logger = logging.getLogger(__name__)


# Task 20：默认相似度阈值（保持 L3-6 的 0.05，避免在没有真实评测数据时主观调整）。
# 调用方可在 retrieve_* / build_*_section_* 上显式覆盖。
RAG_DEFAULT_MIN_SIMILARITY = 0.05
RAG_DEFAULT_TOP_K = 5


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
                "created_at": r.created_at.isoformat() if r.created_at else None,
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
    min_similarity: float = RAG_DEFAULT_MIN_SIMILARITY,
    return_meta: bool = False,
) -> List[dict] | Tuple[List[dict], dict]:
    """检索当前 thread 内与 query 最相似的 top_k 条历史问答。

    Args:
        user_id:        必填，强制隔离
        thread_id:      必填，限定在单 thread 内
        query:          用户当前输入
        top_k:          返回条数（默认 3）
        min_similarity: 低于此相似度丢弃（避免噪音）；默认 RAG_DEFAULT_MIN_SIMILARITY
        return_meta:    True 时返回 (hits, meta)；False 时只返回 hits

    Returns:
        list[{user_input, agent_reply, similarity, created_at}]，按相似度降序
        若 return_meta=True，同时返回 meta dict
            {hits, avg_sim, max_sim, min_sim, top_k, min_similarity, took_ms, mode}
    """
    started = time.perf_counter()
    meta: dict[str, Any] = {
        "mode": "single_thread",
        "user_id": user_id,
        "thread_id": thread_id,
        "query_len": len(query) if query else 0,
        "top_k": top_k,
        "min_similarity": min_similarity,
        "hits": 0,
        "avg_sim": 0.0,
        "max_sim": 0.0,
        "took_ms": 0.0,
    }
    if not user_id or not query:
        meta["took_ms"] = (time.perf_counter() - started) * 1000.0
        logger.debug("rag.retrieve_similar skip user_id=%s thread_id=%s", user_id, thread_id)
        return ([], meta) if return_meta else []

    history = _fetch_thread_history(user_id, thread_id)
    if not history:
        meta["took_ms"] = (time.perf_counter() - started) * 1000.0
        logger.debug("rag.retrieve_similar empty user_id=%s thread_id=%s", user_id, thread_id)
        return ([], meta) if return_meta else []

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
        meta["took_ms"] = (time.perf_counter() - started) * 1000.0
        logger.debug("rag.retrieve_similar tfidf_empty user_id=%s", user_id)
        return ([], meta) if return_meta else []

    query_vec = tfidf[-1]
    history_vecs = tfidf[:-1]
    if history_vecs.shape[0] == 0:
        meta["took_ms"] = (time.perf_counter() - started) * 1000.0
        return ([], meta) if return_meta else []
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
            "created_at": h.get("created_at"),
        })

    meta["hits"] = len(results)
    if results:
        meta["avg_sim"] = sum(r["similarity"] for r in results) / len(results)
        meta["max_sim"] = results[0]["similarity"]
    meta["took_ms"] = (time.perf_counter() - started) * 1000.0
    logger.info(
        "rag.retrieve_similar mode=%s hits=%d avg_sim=%.3f max_sim=%.3f took_ms=%.2f",
        meta["mode"], meta["hits"], meta["avg_sim"], meta["max_sim"], meta["took_ms"],
    )
    return (results, meta) if return_meta else results


# ----------------------------------------------------------------------------
# Prompt 组装：把检索结果拼成 LLM 看得懂的段落
# ----------------------------------------------------------------------------
def build_rag_prompt_section(
    user_id: str,
    thread_id: str,
    query: str,
    top_k: int = 3,
    min_similarity: float = RAG_DEFAULT_MIN_SIMILARITY,
    return_meta: bool = False,
) -> str | Tuple[str, dict]:
    """检索 + 拼成 RAG 段落。

    段落格式（可直接拼到 LLM system prompt）：
        <history>
        1. [用户] xxx
           [回答] yyy
        2. ...
        </history>

    无历史时返回空串（调用方决定是否插入）。
    Task 20：min_similarity 默认值改为模块常量 RAG_DEFAULT_MIN_SIMILARITY（保持 0.05）。
            similarity 数值**不注入** prompt（避免 LLM 把检索评分当事实依据）。
            return_meta=True 时返回 (section, meta)。
    """
    if return_meta:
        hits, meta = retrieve_similar(
            user_id, thread_id, query, top_k=top_k,
            min_similarity=min_similarity, return_meta=True,
        )
    else:
        hits = retrieve_similar(
            user_id, thread_id, query, top_k=top_k,
            min_similarity=min_similarity, return_meta=False,
        )
        meta = {}
    if not hits:
        return ("", meta) if return_meta else ""
    lines = ["<history>"]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. [用户] {h['user_input']}")
        lines.append(f"   [回答] {h['agent_reply']}")
    lines.append("</history>")
    section = "\n".join(lines)
    return (section, meta) if return_meta else section


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
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()


def retrieve_similar_cross_thread(
    user_id: str,
    query: str,
    top_k: int = RAG_DEFAULT_TOP_K,
    min_similarity: float = RAG_DEFAULT_MIN_SIMILARITY,
    exclude_thread_id: Optional[str] = None,
    dedup: bool = True,
    return_meta: bool = False,
) -> List[dict] | Tuple[List[dict], dict]:
    """跨 thread 检索（同一 user 的所有历史问答对里找相似）。

    与 retrieve_similar 的区别：
        - 不按 thread 过滤
        - 默认 exclude_thread_id=当前 thread（chat_node 调用时传），
          防止"刚写的历史"立刻被自己召回造成噪声循环。
        - top_k 默认 5（更多上下文，但靠 min_similarity + rerank-by-LLM 控制质量）

    Args:
        user_id:           必填，强制隔离
        query:             用户当前输入
        top_k:             返回条数（默认 RAG_DEFAULT_TOP_K=5）
        min_similarity:    低于此相似度丢弃（避免噪音）；默认 RAG_DEFAULT_MIN_SIMILARITY
        exclude_thread_id: 排除的 thread（通常传"当前 thread"避免自召回）
        dedup:             True 时按 user_input 归一化去重（保留相似度更高者）
        return_meta:       True 时返回 (hits, meta)

    Returns:
        list[{user_input, agent_reply, similarity, thread_id, created_at}]，按相似度降序
        若 return_meta=True，同时返回 meta dict
            {hits, deduped, avg_sim, max_sim, top_k, min_similarity, took_ms, mode}
    """
    started = time.perf_counter()
    meta: dict[str, Any] = {
        "mode": "cross_thread",
        "user_id": user_id,
        "exclude_thread_id": exclude_thread_id,
        "query_len": len(query) if query else 0,
        "top_k": top_k,
        "min_similarity": min_similarity,
        "hits": 0,
        "deduped": 0,
        "avg_sim": 0.0,
        "max_sim": 0.0,
        "took_ms": 0.0,
    }
    if not user_id or not query:
        meta["took_ms"] = (time.perf_counter() - started) * 1000.0
        logger.debug(
            "rag.retrieve_similar_cross_thread skip user_id=%s", user_id,
        )
        return ([], meta) if return_meta else []

    history = _fetch_user_history(user_id)
    if not history:
        meta["took_ms"] = (time.perf_counter() - started) * 1000.0
        logger.debug(
            "rag.retrieve_similar_cross_thread empty user_id=%s", user_id,
        )
        return ([], meta) if return_meta else []

    # 排除指定 thread
    if exclude_thread_id:
        history = [h for h in history if h["thread_id"] != exclude_thread_id]
    if not history:
        meta["took_ms"] = (time.perf_counter() - started) * 1000.0
        return ([], meta) if return_meta else []

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
        meta["took_ms"] = (time.perf_counter() - started) * 1000.0
        return ([], meta) if return_meta else []

    query_vec = tfidf[-1]
    history_vecs = tfidf[:-1]
    if history_vecs.shape[0] == 0:
        meta["took_ms"] = (time.perf_counter() - started) * 1000.0
        return ([], meta) if return_meta else []
    sims = cosine_similarity(query_vec, history_vecs).flatten()

    ranked = sorted(
        zip(sims, history),
        key=lambda x: x[0],
        reverse=True,
    )
    raw_filtered: list[tuple[float, dict]] = []
    for sim, h in ranked:
        if sim < min_similarity:
            continue
        raw_filtered.append((float(sim), h))
    meta["filtered_out_by_threshold"] = max(0, len(ranked) - len(raw_filtered))

    # Task 20：跨 thread 去重（保留相似度更高者）。
    # 归一化：strip + collapse whitespace。不区分大小写（中文不适用，但英式混合安全）。
    pre_dedup_count = len(raw_filtered)
    results = _dedup_hits(raw_filtered, top_k=top_k) if dedup else _take_top_k(raw_filtered, top_k)
    meta["deduped"] = pre_dedup_count - len(results)

    meta["hits"] = len(results)
    if results:
        meta["avg_sim"] = sum(r["similarity"] for r in results) / len(results)
        meta["max_sim"] = results[0]["similarity"]
    meta["took_ms"] = (time.perf_counter() - started) * 1000.0
    logger.info(
        "rag.retrieve_similar_cross_thread mode=%s hits=%d avg_sim=%.3f max_sim=%.3f took_ms=%.2f",
        meta["mode"], meta["hits"], meta["avg_sim"], meta["max_sim"], meta["took_ms"],
    )
    return (results, meta) if return_meta else results


def _take_top_k(
    ranked: list[tuple[float, dict]],
    top_k: int,
) -> list[dict]:
    """按 (sim, history) 排序后的列表取 top_k，转成结果 dict。"""
    out = []
    for sim, h in ranked[:top_k]:
        out.append({
            "user_input": h["user_input"],
            "agent_reply": h["agent_reply"],
            "similarity": sim,
            "thread_id": h["thread_id"],
            "created_at": h.get("created_at"),
        })
    return out


def _dedup_hits(
    ranked: list[tuple[float, dict]],
    top_k: int,
) -> list[dict]:
    """按 user_input 归一化键去重，保留相似度更高者；最后截 top_k。

    输入 ranked 已按相似度降序，因此"先到先得"等价于"保留最高相似度"。

    Args:
        ranked: [(sim, history_dict), ...]，按 sim 降序
        top_k:  最终返回条数

    Returns:
        list[dict]，按相似度降序，长度 ≤ top_k
    """
    seen: set[str] = set()
    out: list[dict] = []
    for sim, h in ranked:
        key = " ".join((h["user_input"] or "").split()).strip()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "user_input": h["user_input"],
            "agent_reply": h["agent_reply"],
            "similarity": sim,
            "thread_id": h["thread_id"],
            "created_at": h.get("created_at"),
        })
        if len(out) >= top_k:
            break
    return out


def build_rag_prompt_section_cross_thread(
    user_id: str,
    query: str,
    top_k: int = RAG_DEFAULT_TOP_K,
    exclude_thread_id: Optional[str] = None,
    current_thread_id: Optional[str] = None,
    min_similarity: float = RAG_DEFAULT_MIN_SIMILARITY,
    dedup: bool = True,
    return_meta: bool = False,
) -> str | Tuple[str, dict]:
    """跨 thread 检索 + 拼 RAG 段落（L3-6 新增）。

    段落格式（与单 thread 版略有不同，标注来源 thread 让 LLM 知道是历史会话）：
        <history cross_thread=true>
        1. [用户/thread:abc] xxx
           [回答] yyy
        2. ...
        </history>

    无历史时返回空串。
    Task 20：min_similarity 默认值改为 RAG_DEFAULT_MIN_SIMILARITY（保持 0.05）。
            similarity 数值**不注入** prompt（避免 LLM 把检索评分当事实依据）。
            dedup 默认 True：跨 thread 历史可能来自不同时间相似问题。
            return_meta=True 时返回 (section, meta)。
    """
    if return_meta:
        hits, meta = retrieve_similar_cross_thread(
            user_id=user_id,
            query=query,
            top_k=top_k,
            min_similarity=min_similarity,
            exclude_thread_id=exclude_thread_id,
            dedup=dedup,
            return_meta=True,
        )
    else:
        hits = retrieve_similar_cross_thread(
            user_id=user_id,
            query=query,
            top_k=top_k,
            min_similarity=min_similarity,
            exclude_thread_id=exclude_thread_id,
            dedup=dedup,
            return_meta=False,
        )
        meta = {}
    if not hits:
        return ("", meta) if return_meta else ""
    lines = ["<history cross_thread=true>"]
    for i, h in enumerate(hits, 1):
        # 标注：方便 LLM 判断"这是另一会话的历史，不是当前上下文"
        tag = f"thread:{h['thread_id']}"
        if current_thread_id and h["thread_id"] == current_thread_id:
            tag = "thread:current"
        lines.append(f"{i}. [用户/{tag}] {h['user_input']}")
        lines.append(f"   [回答] {h['agent_reply']}")
    lines.append("</history>")
    section = "\n".join(lines)
    return (section, meta) if return_meta else section


__all__ = [
    "save_chat",
    "retrieve_similar",
    "build_rag_prompt_section",
    "retrieve_similar_cross_thread",
    "build_rag_prompt_section_cross_thread",
    "RAG_DEFAULT_MIN_SIMILARITY",
    "RAG_DEFAULT_TOP_K",
]