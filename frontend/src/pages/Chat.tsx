import { useEffect, useRef } from 'react';
import ChatMessage from '../components/ChatMessage';
import ChatInput from '../components/ChatInput';
import AvatarBot from '../components/AvatarBot';
import { useChat } from '../hooks/useChat';

const QUICK_ACTIONS = [
  { label: '记一笔', prompt: '今天午饭花了 35 元' },
  { label: '查消费', prompt: '我最近花了多少钱？' },
  { label: '看分析', prompt: '分析一下我最近的消费' },
  { label: '设置预算', prompt: '帮我设置本月预算为 2000 元' },
];

export default function Chat() {
  const { messages, loading, historyLoading, historyEmpty, hasMessages, send } = useChat({ thread_id: 'main' });
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, loading]);

  return (
    <div className="page page-chat">
      <header className="page-header chat-header">
        <div className="chat-header-inner">
          <span className="chat-title">AI 记账助手</span>
        </div>
      </header>

      {/* 三态渲染：
          1) 拉取中（historyLoading=true）→ 不显示欢迎卡片，等历史回来再渲染
          2) 拉完且确实没历史（historyEmpty=true）→ 显示欢迎卡片
          3) 有历史（hasMessages=true）→ 显示聊天列表
       */}
      {!historyLoading && historyEmpty === true && !hasMessages && (
        <div className="chat-welcome">
          <AvatarBot size={56} />
          <p className="welcome-hi">你好，今天想记录什么呢？</p>
          <p className="welcome-hint">你可以直接说「今天午饭花了 35 元」</p>
          <div className="quick-row">
            {QUICK_ACTIONS.map((q) => (
              <button
                key={q.label}
                className="quick-chip"
                type="button"
                onClick={() => send(q.prompt)}
                disabled={loading}
              >
                {q.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="chat-scroll" ref={listRef}>
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

      <ChatInput onSend={send} loading={loading} />
    </div>
  );
}