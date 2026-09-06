import { request } from './client';
import type { ChatRequest, ChatResponse } from '../types/chat';

export function chat(payload: ChatRequest): Promise<ChatResponse> {
  return request<ChatResponse>('/chat', {
    method: 'POST',
    body: payload,
  });
}

export interface ChatHistoryEntry {
  id: string;
  role: 'user' | 'ai';
  content: string;
  created_at: string | null;
}

/**
 * 拉取指定 thread 的历史问答对。
 * 不传 thread_id 时按后端默认（"AI 记账" 页面对应的 thread）拉取。
 */
export function getHistory(limit = 50, thread_id?: string): Promise<ChatHistoryEntry[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (thread_id) params.set('thread_id', thread_id);
  return request<ChatHistoryEntry[]>(`/chat/history?${params.toString()}`, {
    method: 'GET',
  });
}