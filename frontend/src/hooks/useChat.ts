import { useCallback, useRef, useState } from 'react';
import { chat as chatApi } from '../api/chat';
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

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

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
      const res = await chatApi({ message: trimmed });
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
    setMessages([WELCOME]);
    setLoading(false);
  }, []);

  return { messages, loading, send, reset };
}