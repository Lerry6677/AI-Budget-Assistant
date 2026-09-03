export interface ChatRequest {
  message: string;
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