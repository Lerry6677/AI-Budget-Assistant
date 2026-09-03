import React, { useState } from 'react';

interface Props {
  onSend: (text: string) => void;
  loading: boolean;
}

export default function ChatInput({ onSend, loading }: Props) {
  const [text, setText] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (loading || !text.trim()) return;
    onSend(text);
    setText('');
  };

  return (
    <form className="chat-input-bar" onSubmit={handleSubmit}>
      <input
        className="chat-input"
        placeholder={loading ? 'AI 正在思考…' : '输入消息…'}
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={loading}
        maxLength={4000}
        autoComplete="off"
      />
      <button
        type="submit"
        className={`chat-send ${loading || !text.trim() ? 'is-disabled' : ''}`}
        disabled={loading || !text.trim()}
        aria-label="发送"
      >
        {loading ? (
          <span className="dots">
            <i /> <i /> <i />
          </span>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M5 12h12M13 6l6 6-6 6" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </button>
    </form>
  );
}