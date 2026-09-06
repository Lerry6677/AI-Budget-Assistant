import { useCallback, useEffect, useRef, useState } from 'react';
import { chat as chatApi, getHistory } from '../api/chat';
import type { ChatMessage } from '../types/chat';

let messageId = 0;
function nextId(): string {
  messageId += 1;
  return `${Date.now()}-${messageId}`;
}

const WELCOME: ChatMessage = {
  id: 'welcome',
  role: 'ai',
  content: '你好，今天想记录什么呢？\n试试告诉我你刚才花了什么，比如「今天午饭花了 35 元」。',
  createdAt: Date.now(),
};

export interface UseChatOptions {
  /**
   * 会话空间标识，传入后端以隔离不同页面的对话历史/记忆。
   * 例如 "main"（"AI 记账"页面）、"stats"（"统计"页面）。
   * 不传则按后端默认（f"user_{user_id}"）。
   */
  thread_id?: string;
  /**
   * 开启"前端 only"模式：会话历史只缓存在浏览器 sessionStorage，不写入数据库。
   * - 传入非空字符串作为 storage key（不同 key 互不干扰）
   * - 刷新页面 / 切回 tab 不会丢失
   * - 关闭浏览器 / 切换账号 / 切换浏览器则丢失
   *
   * 适用场景：希望某页面（如"统计"）拥有完全独立的对话空间，
   * 且不污染其他页面/账号的数据库历史。
   */
  storageKey?: string;
}

/**
 * 从 sessionStorage 读取已缓存的消息。
 * 读取失败或解析失败时返回空数组。
 */
function loadFromStorage(key: string): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return [];
    const arr = JSON.parse(raw) as ChatMessage[];
    if (!Array.isArray(arr)) return [];
    return arr;
  } catch {
    return [];
  }
}

export function useChat(options: UseChatOptions = {}) {
  const threadId = options.thread_id;
  const storageKey = options.storageKey;
  const localOnly = Boolean(storageKey);

  // 初始 messages：
  //   - 启用 storageKey 时从 sessionStorage 立即恢复（同步），无刷新闪烁；
  //   - 否则从空数组起步，靠 useEffect 异步拉后端。
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    localOnly ? loadFromStorage(storageKey!) : [],
  );
  const [loading, setLoading] = useState(false);
  // historyLoading：正在从后端拉历史
  // historyEmpty：拉历史的结果（null=未知/拉取中，true=确实没历史）
  // 拆分这两个字段可以让 UI 在"加载中" / "无历史-显示欢迎卡片" / "有历史-显示对话" 三种状态间清晰切换，
  // 避免出现"先显示欢迎卡片再被替换"的闪烁。
  const [historyLoading, setHistoryLoading] = useState(!localOnly);
  const [historyEmpty, setHistoryEmpty] = useState<boolean | null>(
    localOnly ? messages.length === 0 : null,
  );
  const abortRef = useRef<AbortController | null>(null);

  // 把 messages 同步到 sessionStorage（仅在 localOnly 模式下）
  useEffect(() => {
    if (!localOnly) return;
    try {
      sessionStorage.setItem(storageKey!, JSON.stringify(messages));
    } catch {
      // sessionStorage 可能被禁用或超限（5MB），忽略即可
    }
  }, [messages, localOnly, storageKey]);

  // 组件挂载时从后端拉历史问答，刷新页面后能保留记录。
  // localOnly 模式下跳过这一步（已经在 useState 初始化时从 sessionStorage 恢复）。
  useEffect(() => {
    if (localOnly) return;
    let cancelled = false;
    (async () => {
      try {
        const rows = await getHistory(50, threadId);
        if (cancelled) return;
        if (rows.length === 0) {
          setHistoryEmpty(true);
          return;
        }
        const restored: ChatMessage[] = rows.map((row) => ({
          id: row.id,
          role: row.role,
          content: row.content,
          createdAt: row.created_at ? new Date(row.created_at).getTime() : Date.now(),
        }));
        setMessages(restored);
        setHistoryEmpty(false);
      } catch {
        // 拉历史失败时静默忽略，按"无历史"处理（显示欢迎卡片）
        setHistoryEmpty(true);
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [threadId, localOnly]);

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    // 简单过滤：纯数字 / 单字符 / 表情符号等无意义输入不再调用后端，
    // 避免在 chat_history 里留下一堆"您好有什么可以帮您"之类的噪音。
    if (/^[\d\W_]+$/.test(trimmed) && trimmed.length <= 2) return;

    const userMsg: ChatMessage = {
      id: nextId(),
      role: 'user',
      content: trimmed,
      createdAt: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await chatApi({ message: trimmed, thread_id: threadId });
      const aiMsg: ChatMessage = {
        id: nextId(),
        role: 'ai',
        content: res.answer,
        createdAt: Date.now(),
      };
      setMessages((prev) => [...prev, aiMsg]);
    } catch (err) {
      const message =
        err instanceof Error && err.message
          ? err.message
          : '抱歉，AI 暂时无法回答，请稍后再试。';
      const errAi: ChatMessage = {
        id: nextId(),
        role: 'ai',
        content: message,
        createdAt: Date.now(),
      };
      setMessages((prev) => [...prev, errAi]);
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }, [loading]);

  const reset = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    setMessages([]);
    setHistoryEmpty(true);
    setHistoryLoading(false);
    setLoading(false);
  }, []);

  return {
    messages,
    loading,
    historyLoading,
    historyEmpty,
    hasMessages: messages.length > 0,
    send,
    reset,
  };
}