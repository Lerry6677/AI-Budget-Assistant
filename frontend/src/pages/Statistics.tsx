import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client';
import { chat as chatApi } from '../api/chat';
import AvatarBot from '../components/AvatarBot';

// Statistics page deliberately leverages the existing /chat endpoint
// (see PRD §【十九、真实数据】): we do NOT fabricate numbers on the frontend.
// We display the AI's textual answer verbatim, plus a small "ask AI" panel.

const PRESETS = [
  '我这个月花了多少钱？',
  '分析一下我最近的消费',
  '本月各类别占比是多少？',
  '我最近一周的消费趋势？',
];

export default function Statistics() {
  const [prompt, setPrompt] = useState('');
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Auto-ask once so the page is not empty on first entry.
    ask(PRESETS[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ask = async (text: string) => {
    const q = text.trim();
    if (!q || loading) return;
    setPrompt(q);
    setError(null);
    setAnswer(null);
    setLoading(true);
    try {
      const res = await chatApi({ message: q });
      setAnswer(res.answer);
    } catch (err) {
      if (err instanceof ApiError) setError(err.detail);
      else setError('请求失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page page-stats">
      <header className="page-header">
        <span className="page-title">统计</span>
      </header>

      <div className="stats-body">
        <div className="stats-presets">
          {PRESETS.map((q) => (
            <button
              key={q}
              className={`preset-chip ${prompt === q ? 'is-active' : ''}`}
              onClick={() => ask(q)}
              disabled={loading}
              type="button"
            >
              {q}
            </button>
          ))}
        </div>

        <div className="stats-card">
          <div className="stats-card-head">
            <AvatarBot size={28} />
            <span className="stats-card-title">AI 分析</span>
          </div>
          <div className="stats-question">{prompt || '点击上面的提示词快速提问'}</div>
          <div className="stats-divider" />
          {loading && (
            <div className="stats-loading">
              <span className="dots big"><i /><i /><i /></span>
              <span>正在为你分析…</span>
            </div>
          )}
          {error && <div className="stats-error">{error}</div>}
          {answer && !loading && <div className="stats-answer">{answer}</div>}
          {!answer && !loading && !error && (
            <div className="stats-empty">还没有数据，问点什么吧。</div>
          )}
        </div>
      </div>

      <form
        className="chat-input-bar"
        onSubmit={(e) => {
          e.preventDefault();
          if (inputRef.current) ask(inputRef.current.value);
        }}
      >
        <input
          ref={inputRef}
          className="chat-input"
          placeholder="问点关于你的消费…"
          disabled={loading}
          maxLength={4000}
        />
        <button
          type="submit"
          className={`chat-send ${loading ? 'is-disabled' : ''}`}
          disabled={loading}
          aria-label="发送"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M5 12h12M13 6l6 6-6 6" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>
    </div>
  );
}