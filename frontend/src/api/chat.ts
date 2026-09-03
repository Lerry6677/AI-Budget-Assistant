import { request } from './client';
import type { ChatRequest, ChatResponse } from '../types/chat';

export function chat(payload: ChatRequest): Promise<ChatResponse> {
  return request<ChatResponse>('/chat', {
    method: 'POST',
    body: payload,
  });
}