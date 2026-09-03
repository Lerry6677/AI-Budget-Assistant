import AvatarBot from './AvatarBot';
import type { ChatMessage as ChatMessageType } from '../types/chat';

interface Props {
  message: ChatMessageType;
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}

export default function ChatMessage({ message }: Props) {
  const isAi = message.role === 'ai';
  return (
    <div className={`msg-row ${isAi ? 'msg-ai' : 'msg-user'}`}>
      {isAi && (
        <div className="msg-avatar">
          <AvatarBot size={32} />
        </div>
      )}
      <div className={`msg-bubble ${isAi ? 'bubble-ai' : 'bubble-user'}`}>
        <div className="msg-content">{message.content}</div>
        <div className="msg-time">{formatTime(message.createdAt)}</div>
      </div>
    </div>
  );
}