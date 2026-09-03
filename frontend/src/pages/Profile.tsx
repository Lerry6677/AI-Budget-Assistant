import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import AvatarBot from '../components/AvatarBot';

interface RowItem {
  label: string;
  path?: string;
  danger?: boolean;
}

const ROWS: RowItem[] = [
  { label: '历史记录', path: '/chat' },
  { label: '预算管理', path: '/chat' },
  { label: '分类管理', path: '/chat' },
  { label: '设置', path: '/chat' },
];

export default function Profile() {
  const navigate = useNavigate();
  const { username, logout } = useAuth();

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="page page-profile">
      <header className="page-header">
        <span className="page-title">我的</span>
      </header>

      <div className="profile-body">
        <div className="profile-hero">
          <div className="profile-avatar">
            <AvatarBot size={56} />
          </div>
          <div className="profile-meta">
            <div className="profile-name">{username || '未登录'}</div>
            <div className="profile-sub">让记账更简单，生活更轻松</div>
          </div>
          <span className="profile-arrow">›</span>
        </div>

        <div className="profile-card">
          {ROWS.map((row, idx) => (
            <button
              key={row.label}
              className="profile-row"
              type="button"
              onClick={() => row.path && navigate(row.path)}
            >
              <span className="profile-row-label">{row.label}</span>
              <span className="profile-row-arrow">›</span>
              {idx < ROWS.length - 1 && <span className="profile-divider" />}
            </button>
          ))}
        </div>

        <button className="logout-btn" type="button" onClick={handleLogout}>
          退出登录
        </button>
      </div>
    </div>
  );
}