export interface ChatRequest {
  message: string;
  // 可选会话空间标识：让"AI 记账"与"统计"页面之间互不污染对话历史。
  // 后端会用它替代默认的 f"user_{user_id}" 作为 thread_id。
  thread_id?: string;
}

export interface ChatResponse {
  answer: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  content: string;
  createdAt: number;
}