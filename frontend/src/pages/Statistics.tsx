import { useCallback } from 'react';
import AvatarBot from '../components/AvatarBot';
import ChatMessage from '../components/ChatMessage';
import ChatInput from '../components/ChatInput';
import { useChat } from '../hooks/useChat';

// 统计页：完全独立的"会话空间"。
// - 复用 useChat，但用 storageKey 启用"前端 only"模式：
//   历史只缓存在浏览器 sessionStorage，不写入数据库。
// - 关闭/刷新页面 / 切回 tab 不会丢失。
// - thread_id 使用 "local:stats" 前缀：后端 agent 会据此跳过 chat_history 写库。
const STORAGE_KEY = 'stats_chat_session_v1';

const PRESETS = [
  '我这个月花了多少钱？',
  '分析一下我最近的消费',
  '本月各类别占比是多少？',
  '我最近一周的消费趋势？',
];

export default function Statistics() {
  const {
    messages,
    loading,
    historyLoading,
    historyEmpty,
    hasMessages,
    send: sendViaHook,
  } = useChat({ thread_id: 'local:stats', storageKey: STORAGE_KEY });

  const ask = useCallback(
    async (text: string) => {
      const q = text.trim();
      if (!q || loading) return;
      await sendViaHook(q);
    },
    [loading, sendViaHook],
  );

  return (
    <div className="page page-stats">
      <header className="page-header">
        <span className="page-title">统计</span>
      </header>

      {/* 三态渲染：拉历史 → 骨架；无历史 → 欢迎卡片；已有历史 → 聊天列表 */}
      {!historyLoading && historyEmpty === true && !hasMessages && (
        <div className="chat-welcome">
          <AvatarBot size={56} />
          <p className="welcome-hi">统计</p>
          <p className="welcome-hint">
            你可以直接问，也可以点下面的提示词快速开始
          </p>
          <div className="quick-row">
            {PRESETS.map((q) => (
              <button
                key={q}
                className="quick-chip"
                type="button"
                onClick={() => ask(q)}
                disabled={loading}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="chat-scroll">
        <div className="chat-list">
          {historyLoading && hasMessages === false && historyEmpty === null && (
            <div className="msg-row msg-ai">
              <div className="msg-avatar">
                <AvatarBot size={32} />
              </div>
              <div className="msg-bubble bubble-ai">
                <span className="dots big">
                  <i /> <i /> <i />
                </span>
              </div>
            </div>
          )}
          {messages.map((m) => (
            <ChatMessage key={m.id} message={m} />
          ))}
          {loading && (
            <div className="msg-row msg-ai">
              <div className="msg-avatar">
                <AvatarBot size={32} />
              </div>
              <div className="msg-bubble bubble-ai">
                <span className="dots big">
                  <i /> <i /> <i />
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      <ChatInput onSend={ask} loading={loading} />
    </div>
  );
}